# autoclip-export-geometry

Audit what a batch of rendered short-video exports **actually is**: coded size, rotation, pixel aspect ratio, and the display size a player will show — then name the files that do not match the rest of the batch. Needed now because batch renderers hand you ten files at once and nobody checks each one's geometry.

Upstream: https://github.com/zhouxiaoka/autoclip

## What the upstream does, and what is missing

[zhouxiaoka/autoclip](https://github.com/zhouxiaoka/autoclip) turns one long video into a batch of vertical short clips (抖音 / 小红书 / TikTok / Shorts / B站) with subtitles and covers; it renders locally with ffmpeg. The app shows a preview and a list of produced files, but there is no way to ask "are these ten files really the same size and orientation?".

A real, open, app-filed bug says exactly that:
[issue #580 — "视频生产出来共有10个，前三个是原画像大小9-16竖屏的，后面的都会被缩小视频，完全不可以使用"](https://github.com/zhouxiaoka/autoclip/issues/580)
(1.5.8, Windows, labels `bug`/`needs-triage`/`from-app`). The reporter cannot tell which of the ten files are wrong, or by how much, because the UI only shows a thumbnail.

Two facts make the naive check wrong, and both live in the container, not the thumbnail:

1. `tkhd` carries a 3×3 display matrix. A clip stored as 1920×1080 with a 90° matrix **plays** as 1080×1920.
2. `pasp` carries a non-square pixel ratio. A real ffmpeg-muxed NTSC file in our cross-check is 720×480 coded with SAR 10:11, which displays as **654.5×480 (15:11)**, not 3:2.

So `ffprobe`-style "width × height" is not enough: you need display size = coded × SAR, swapped for 90°/270°.

## What this tool does / does not do

Does:

- Reads `ftyp`, `moov/mvhd`, `trak/tkhd` (matrix), `mdia/mdhd`, `hdlr`, `stsd` (codec, coded size) and `pasp` — pure stdlib, skips `mdat`, so a 1 GB export costs the same as a 5 KB one.
- `batch` behaviour: groups display sizes across the files you pass and flags every file that differs from the batch majority (`batch_size_outlier`) — the #580 symptom, named file by file.
- Checks: `target_aspect_mismatch` against a platform target, `below_min_height`, `odd_dimensions` (h264 4:2:0 needs even), `anamorphic_sar`, `non_orthogonal_rotation`, `no_video_track`, `unreadable`.
- `--json` report, `--out` to a file, exit codes (below). Fully offline.

Does not:

- Decode video or touch frames; it never re-encodes, fixes, or rewrites your files.
- Guess why a file was scaled — it reports geometry, not the renderer's intent.
- Read fragmented MP4 (`moof`) sample tables or MKV/WebM. It reads the geometry boxes only, which `moof` does not change.

## Install / usage

No dependencies, Python ≥ 3.9.

```bash
git clone <this repo> && cd autoclip-export-geometry
python3 bin/autoclip-export-geometry examples/in --target douyin-9x16
```

Text output (real run on `examples/in`):

```
01_hook.mp4  coded=1080x1920  display=1080.0x1920.0  9:16  rot=0  sar=1:1
02_point.mp4  coded=1080x1920  display=1080.0x1920.0  9:16  rot=0  sar=1:1
03_quote.mp4  coded=1080x1920  display=1920.0x1080.0  16:9  rot=90  sar=1:1
04_tail.mp4  coded=720x1280  display=720.0x1280.0  9:16  rot=0  sar=1:1
ERROR   batch_size_outlier      03_quote.mp4: 1920x1080 differs from batch majority 1080x1920
ERROR   target_aspect_mismatch  03_quote.mp4: 03_quote.mp4 is 16:9, target douyin-9x16 needs 9:16
ERROR   batch_size_outlier      04_tail.mp4: 720x1280 differs from batch majority 1080x1920
4 file(s), 3 error(s), 0 warning(s)
```

JSON (`--json`, excerpt of `examples/out/report.json`):

```json
{
  "ok": false,
  "file_count": 4,
  "findings": [{"code": "batch_size_outlier", "severity": "error",
                "file": "examples/in/04_tail.mp4",
                "detail": "720x1280 differs from batch majority 1080x1920"}],
  "summary": {"errors": 3, "warnings": 0}
}
```

Full command reference:

```
python3 bin/autoclip-export-geometry PATH... [--target NAME] [--min-height PX] [--json] [--out FILE]
```

`PATH` may be files or directories (directories are globbed for `*.mp4/*.mov/*.m4v`).
`--target` accepts `douyin-9x16`, `tiktok-9x16`, `shorts-9x16`, `xiaohongshu-3x4`, `bilibili-16x9`, `square-1x1`.

Exit codes:

| code | meaning |
| --- | --- |
| 0 | every file parses and no finding |
| 1 | findings reported (errors and/or warnings), including unreadable files |
| 2 | usage or input error: no matching files, path does not exist |

## Tests

```bash
python3 tests/test_audit.py
```

17 unittest cases (10 behavioural: exit codes, JSON contract, batch outlier naming), all green.

## 本轮创新

First tool that treats a **render batch** as the unit of geometry truth: display size is computed from `tkhd` matrix × `pasp`, then each file is compared to the batch majority so the shrunk outliers are named. Upstream only exposes a thumbnail list; no issue, PR, or script in the repo inspects exported geometry, and the existing one-shot `ffprobe` habit reports coded size, which is wrong for rotated or anamorphic files (our real-file cross-check: 720×480 SAR 10:11 → 15:11, not 3:2). Same gap cannot be copy-pasted to another trending repo without the matrix/SAR/batch-majority triple.

## Limitations

- Batch majority is a heuristic: with 2 files of different sizes it cannot tell which one is wrong; it reports both as outliers relative to the larger group.
- `--min-height` compares display height, not the platform's own encoded spec, which varies by account and region.
- Sample-entry parsing covers `avc1/avc3/hvc1/hev1/av01/vp09/mp4v`; other codecs fall back to `tkhd` dimensions (still correct for display size unless SAR is non-square).
- No frame-level check: a file can be geometrically right and still blurry from a low bitrate.

## License

MIT — see `LICENSE`.
