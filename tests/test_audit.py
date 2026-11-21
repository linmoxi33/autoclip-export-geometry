import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from autoclip_export_geometry.audit import audit, display_size  # noqa: E402
from autoclip_export_geometry.mp4 import parse  # noqa: E402
from fixtures import write_mp4  # noqa: E402

BIN = os.path.join(ROOT, "bin", "autoclip-export-geometry")


def run(args):
    proc = subprocess.run([sys.executable, BIN] + args, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class GeometryParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.tmp, name)

    def test_coded_size_is_read(self):
        p = write_mp4(self.path("a.mp4"), 1080, 1920)
        tr = parse(p)["tracks"][0]
        self.assertEqual((tr["coded_width"], tr["coded_height"]), (1080, 1920))
        self.assertEqual(tr["codec"], "avc1")
        self.assertEqual(tr["handler"], "vide")

    def test_rotation_90_swaps_display_size(self):
        p = write_mp4(self.path("b.mp4"), 1080, 1920, rotation=90)
        tr = parse(p)["tracks"][0]
        self.assertEqual(tr["rotation"], 90)
        self.assertEqual(display_size(tr), (1920.0, 1080.0))

    def test_rotation_180_does_not_swap(self):
        p = write_mp4(self.path("c.mp4"), 1080, 1920, rotation=180)
        tr = parse(p)["tracks"][0]
        self.assertEqual(tr["rotation"], 180)
        self.assertEqual(display_size(tr), (1080.0, 1920.0))

    def test_anamorphic_sar_changes_display_width(self):
        p = write_mp4(self.path("d.mp4"), 720, 480, sar=(2, 1))
        tr = parse(p)["tracks"][0]
        self.assertEqual(tr["sar"], {"h": 2, "v": 1})
        self.assertEqual(display_size(tr), (1440.0, 480.0))
        entry = audit([p])["files"][0]["video_tracks"][0]
        self.assertEqual(entry["dar"], "3:1")  # 1440x480

    def test_audio_track_is_not_a_video_track(self):
        p = write_mp4(self.path("e.mp4"), 1080, 1920, audio=True)
        kinds = [t["handler"] for t in parse(p)["tracks"]]
        self.assertEqual(kinds, ["vide", "soun"])
        self.assertEqual(len(audit([p])["files"][0]["video_tracks"]), 1)

    def test_hvc1_codec_is_recognised(self):
        p = write_mp4(self.path("f.mp4"), 1080, 1920, codec="hvc1")
        entry = audit([p])["files"][0]["video_tracks"][0]
        self.assertEqual(entry["codec"], "hvc1")
        self.assertEqual(entry["display_height"], 1920.0)


class BatchFindings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.tmp, name)

    def test_batch_size_outlier_is_named(self):
        a = write_mp4(self.path("01.mp4"), 1080, 1920)
        b = write_mp4(self.path("02.mp4"), 1080, 1920)
        c = write_mp4(self.path("03.mp4"), 720, 1280)
        rep = audit([a, b, c])
        self.assertFalse(rep["ok"])
        codes = {(f["code"], os.path.basename(f["file"])) for f in rep["findings"]}
        self.assertIn(("batch_size_outlier", "03.mp4"), codes)
        self.assertNotIn(("batch_size_outlier", "01.mp4"), codes)

    def test_clean_batch_has_no_findings(self):
        a = write_mp4(self.path("01.mp4"), 1080, 1920)
        b = write_mp4(self.path("02.mp4"), 1080, 1920, audio=True)
        self.assertTrue(audit([a, b])["ok"])

    def test_target_aspect_mismatch(self):
        p = write_mp4(self.path("x.mp4"), 1080, 1920)
        rep = audit([p], target="xiaohongshu-3x4")
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["findings"][0]["code"], "target_aspect_mismatch")

    def test_min_height_floor(self):
        p = write_mp4(self.path("low.mp4"), 720, 1280)
        rep = audit([p], min_height=1920)
        self.assertEqual([f["code"] for f in rep["findings"]], ["below_min_height"])

    def test_odd_dimensions_warn(self):
        p = write_mp4(self.path("odd.mp4"), 1081, 1921)
        rep = audit([p])
        self.assertEqual([f["code"] for f in rep["findings"]], ["odd_dimensions"])
        self.assertEqual(rep["summary"], {"errors": 0, "warnings": 1})


class CliContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.tmp, name)

    def test_exit_0_on_clean_batch(self):
        write_mp4(self.path("a.mp4"), 1080, 1920)
        write_mp4(self.path("b.mp4"), 1080, 1920)
        rc, out, _ = run([self.tmp])
        self.assertEqual(rc, 0)
        self.assertIn("0 error(s)", out)

    def test_exit_1_on_findings_and_json_parses(self):
        write_mp4(self.path("a.mp4"), 1080, 1920)
        write_mp4(self.path("b.mp4"), 1080, 1920)
        write_mp4(self.path("c.mp4"), 720, 1280)
        rc, out, _ = run([self.tmp, "--json"])
        self.assertEqual(rc, 1)
        rep = json.loads(out)
        self.assertEqual(rep["summary"]["errors"], 1)
        self.assertEqual(rep["file_count"], 3)

    def test_exit_2_on_missing_file(self):
        rc, _, err = run([self.path("nope.mp4")])
        self.assertEqual(rc, 2)
        self.assertIn("no such file", err)

    def test_exit_2_on_non_mp4(self):
        bad = self.path("bad.mp4")
        with open(bad, "wb") as fh:
            fh.write(b"not a video at all, just text bytes" * 3)
        rc, out, _ = run([bad, "--json"])
        self.assertEqual(rc, 1)
        rep = json.loads(out)
        self.assertEqual(rep["findings"][0]["code"], "unreadable")

    def test_exit_2_on_empty_directory(self):
        empty = self.path("empty")
        os.makedirs(empty)
        rc, _, err = run([empty])
        self.assertEqual(rc, 2)
        self.assertIn("no MP4", err)

    def test_out_writes_report_file(self):
        write_mp4(self.path("a.mp4"), 1080, 1920)
        out_path = self.path("report.json")
        rc, _, _ = run([self.tmp, "--json", "--out", out_path])
        self.assertEqual(rc, 0)
        with open(out_path) as fh:
            rep = json.load(fh)
        self.assertEqual(rep["files"][0]["video_tracks"][0]["display_height"], 1920.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
