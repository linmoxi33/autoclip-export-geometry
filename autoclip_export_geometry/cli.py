"""CLI: 0 = clean, 1 = findings, 2 = usage/input error."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from .audit import TARGETS, audit
from .mp4 import Mp4Error


def _expand(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for ext in ("*.mp4", "*.mov", "*.m4v", "*.MP4", "*.MOV"):
                out.extend(sorted(glob.glob(os.path.join(p, ext))))
        else:
            out.append(p)
    seen, uniq = set(), []
    for p in out:
        key = os.path.realpath(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autoclip-export-geometry",
                                 description="Audit the real geometry of a batch of rendered exports.")
    ap.add_argument("paths", nargs="+", help="MP4/MOV files or directories")
    ap.add_argument("--target", choices=sorted(TARGETS), help="platform aspect target")
    ap.add_argument("--min-height", type=int, default=None, help="required display height in px")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--out", help="write the JSON report to this path")
    args = ap.parse_args(argv)

    files = _expand(args.paths)
    if not files:
        print("error: no MP4/MOV files matched", file=sys.stderr)
        return 2
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        for f in missing:
            print("error: no such file: %s" % f, file=sys.stderr)
        return 2

    report = audit(files, target=args.target, min_height=args.min_height)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        for entry in report["files"]:
            if entry["video_tracks"]:
                tr = entry["video_tracks"][0]
                print("%s  coded=%dx%d  display=%sx%s  %s  rot=%d  sar=%s"
                      % (os.path.basename(entry["path"]), tr["coded_width"], tr["coded_height"],
                         tr["display_width"], tr["display_height"], tr["dar"], tr["rotation"], tr["sar"]))
            else:
                print("%s  (no video track)" % os.path.basename(entry["path"]))
        for f in report["findings"]:
            print("%-7s %-24s %s: %s" % (f["severity"].upper(), f["code"], os.path.basename(f["file"]), f["detail"]))
        print("%d file(s), %d error(s), %d warning(s)"
              % (report["file_count"], report["summary"]["errors"], report["summary"]["warnings"]))
    return 0 if report["ok"] else 1
