"""Batch geometry audit: which exports in one render batch are the odd ones out."""
from __future__ import annotations

from fractions import Fraction

from .mp4 import Mp4Error, parse

TARGETS = {
    "douyin-9x16": (9, 16),
    "xiaohongshu-3x4": (3, 4),
    "tiktok-9x16": (9, 16),
    "shorts-9x16": (9, 16),
    "bilibili-16x9": (16, 9),
    "square-1x1": (1, 1),
}


def display_size(track: dict) -> tuple:
    """Display size = coded size * SAR, then swapped for 90/270 rotation."""
    sar = track.get("sar") or {"h": 1, "v": 1}
    w = track.get("coded_width") or int(round(track.get("tkhd_width") or 0))
    h = track.get("coded_height") or int(round(track.get("tkhd_height") or 0))
    num, den = sar.get("h", 1), sar.get("v", 1)
    dw = w * num / den
    dh = float(h)
    if track.get("rotation") in (90, 270):
        dw, dh = dh, dw
    return dw, dh


def _ratio(num: float, den: float) -> str:
    if den == 0:
        return "0:1"
    frac = Fraction(num / den).limit_denominator(100)
    return "%d:%d" % (frac.numerator, frac.denominator)


def audit_file(path: str) -> dict:
    info = parse(path)
    videos = [t for t in info["tracks"] if t.get("handler") == "vide" and (t.get("coded_width") or t.get("tkhd_width"))]
    entry = {"path": path, "brands": info["brands"], "video_tracks": []}
    for t in videos:
        dw, dh = display_size(t)
        sar = t.get("sar") or {"h": 1, "v": 1}
        entry["video_tracks"].append({
            "track_id": t.get("track_id"),
            "codec": t.get("codec"),
            "coded_width": int(t.get("coded_width") or 0),
            "coded_height": int(t.get("coded_height") or 0),
            "display_width": round(dw, 3),
            "display_height": round(dh, 3),
            "dar": _ratio(dw, dh),
            "sar": "%d:%d" % (sar.get("h", 1), sar.get("v", 1)),
            "rotation": t.get("rotation", 0),
            "duration_s": round((t.get("mdhd") or {}).get("seconds", 0.0), 3),
        })
    return entry


def audit(paths, target: str = None, min_height: int = None) -> dict:
    files, findings = [], []
    for p in paths:
        try:
            entry = audit_file(p)
        except Mp4Error as exc:
            findings.append({"code": "unreadable", "severity": "error", "file": p, "detail": str(exc)})
            continue
        files.append(entry)
        if not entry["video_tracks"]:
            findings.append({"code": "no_video_track", "severity": "error", "file": p,
                             "detail": "no video track with a declared size"})
            continue
        tr = entry["video_tracks"][0]
        if tr["coded_width"] % 2 or tr["coded_height"] % 2:
            findings.append({"code": "odd_dimensions", "severity": "warn", "file": p,
                             "detail": "coded %dx%d is odd; h264 4:2:0 needs even dimensions"
                                       % (tr["coded_width"], tr["coded_height"])})
        if tr["rotation"] not in (0, 90, 180, 270):
            findings.append({"code": "non_orthogonal_rotation", "severity": "warn", "file": p,
                             "detail": "tkhd matrix rotation is %d degrees" % tr["rotation"]})
        if tr["sar"] not in ("1:1",):
            findings.append({"code": "anamorphic_sar", "severity": "warn", "file": p,
                             "detail": "SAR %s: reported coded size is not what a player shows" % tr["sar"]})
        if target:
            want = TARGETS[target]
            got = tr["display_width"] / tr["display_height"] if tr["display_height"] else 0
            exp = want[0] / want[1]
            if abs(got - exp) > 0.01:
                findings.append({"code": "target_aspect_mismatch", "severity": "error", "file": p,
                                 "detail": "%s is %s, target %s needs %s"
                                           % (p, tr["dar"], target, _ratio(*want))})
        if min_height and tr["display_height"] < min_height:
            findings.append({"code": "below_min_height", "severity": "error", "file": p,
                             "detail": "display height %d < required %d" % (tr["display_height"], min_height)})

    sizes = {}
    for entry in files:
        if entry["video_tracks"]:
            tr = entry["video_tracks"][0]
            key = (tr["display_width"], tr["display_height"])
            sizes.setdefault(key, []).append(entry["path"])
    if len(sizes) > 1:
        majority = max(sizes.items(), key=lambda kv: len(kv[1]))[0]
        for size, members in sizes.items():
            for p in members:
                if size != majority:
                    findings.append({"code": "batch_size_outlier", "severity": "error", "file": p,
                                     "detail": "%dx%d differs from batch majority %dx%d"
                                               % (size[0], size[1], majority[0], majority[1])})

    findings.sort(key=lambda f: (f["file"], f["code"]))
    return {"ok": not findings, "file_count": len(files), "target": target,
            "min_height": min_height, "files": files, "findings": findings,
            "summary": {"errors": sum(1 for f in findings if f["severity"] == "error"),
                        "warnings": sum(1 for f in findings if f["severity"] == "warn")}}
