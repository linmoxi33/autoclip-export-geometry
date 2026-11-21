"""Minimal, dependency-free ISO-BMFF reader for the geometry boxes only.

Reads: ftyp, moov/mvhd, moov/trak/tkhd, mdia/mdhd, mdia/hdlr,
minf/stbl/stsd (codec + coded size + pasp). Every other box is skipped,
so a 100 MB export costs the same as a 5 MB one: we never read mdat payload.
"""
from __future__ import annotations

import struct

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf"}

IDENTITY = (0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)


class Mp4Error(ValueError):
    pass


def _boxes(data: bytes, start: int, end: int):
    """Yield (type, payload_start, payload_end) for boxes in [start, end)."""
    i = start
    while i + 8 <= end:
        size = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        header = 8
        if size == 1:
            if i + 16 > end:
                raise Mp4Error("truncated 64-bit box header at %d" % i)
            size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            header = 16
        elif size == 0:
            size = end - i
        if size < header or i + size > end:
            raise Mp4Error("bad box size %d for %r at %d" % (size, typ, i))
        yield typ, i + header, i + size
        i += size


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Mp4Error("cannot read %s: %s" % (path, exc))


def _rotation(matrix) -> int:
    a, b = matrix[0], matrix[1]
    if a == 0x00010000 and b == 0:
        return 0
    if a == 0 and b == 0x00010000:
        return 90
    if a == -0x00010000 or a == 0xFFFF0000:
        return 180
    if a == 0 and (b == -0x00010000 or b == 0xFFFF0000):
        return 270
    return 0


def _parse_tkhd(payload: bytes) -> dict:
    if len(payload) < 84:
        raise Mp4Error("short tkhd")
    version = payload[0]
    if version == 1:
        track_id = struct.unpack(">I", payload[20:24])[0]
        width = struct.unpack(">I", payload[88:92])[0] / 65536.0
        height = struct.unpack(">I", payload[92:96])[0] / 65536.0
        mstart = 56
    else:
        track_id = struct.unpack(">I", payload[12:16])[0]
        width = struct.unpack(">I", payload[76:80])[0] / 65536.0
        height = struct.unpack(">I", payload[80:84])[0] / 65536.0
        mstart = 40
    matrix = tuple(struct.unpack(">i", payload[mstart + 4 * k:mstart + 4 * k + 4])[0] for k in range(9))
    return {"track_id": track_id, "tkhd_width": width, "tkhd_height": height,
            "matrix": matrix, "rotation": _rotation(matrix)}


def _parse_mdhd(payload: bytes) -> dict:
    version = payload[0]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", payload[20:32])
    else:
        timescale, duration = struct.unpack(">II", payload[12:20])
    return {"timescale": timescale, "duration": duration,
            "seconds": (duration / timescale) if timescale else 0.0}


VIDEO_CODECS = {"avc1", "avc3", "hvc1", "hev1", "av01", "vp09", "mp4v", "dvh1", "dvhe"}


def _parse_stsd(payload: bytes):
    if len(payload) < 8:
        return None
    count = struct.unpack(">I", payload[4:8])[0]
    if count < 1 or len(payload) < 16:
        return None
    entry_size = struct.unpack(">I", payload[8:12])[0]
    fourcc = payload[12:16].decode("latin-1")
    if fourcc not in VIDEO_CODECS:
        return {"codec": fourcc, "coded_width": 0, "coded_height": 0,
                "sar": {"h": 1, "v": 1}, "visual": False}
    entry = payload[8:8 + entry_size]
    if len(entry) < 86:
        return {"codec": fourcc, "coded_width": 0, "coded_height": 0,
                "sar": {"h": 1, "v": 1}, "visual": True}
    # VisualSampleEntry: width/height at offset 32 (after 8 header + 6 reserved + 2 dri + 16 predef)
    width, height = struct.unpack(">HH", entry[32:36])
    sar = {"h": 1, "v": 1}
    for typ, s, e in _boxes(entry, 86, len(entry)):
        if typ == b"pasp" and e - s >= 8:
            h, v = struct.unpack(">II", entry[s:s + 8])
            if h and v:
                sar = {"h": h, "v": v}
    return {"codec": fourcc, "coded_width": width, "coded_height": height, "sar": sar, "visual": True}


def parse(path: str) -> dict:
    data = _read(path)
    if len(data) < 16:
        raise Mp4Error("not an MP4: file too short")
    top = list(_boxes(data, 0, len(data)))
    types = [t for t, _, _ in top]
    if b"ftyp" not in types:
        raise Mp4Error("not an MP4: no ftyp box")
    brands = []
    for typ, s, e in top:
        if typ == b"ftyp":
            major = data[s:s + 4].decode("latin-1")
            compat = [data[k:k + 4].decode("latin-1") for k in range(s + 8, e - 3, 4)]
            brands = [major] + compat
            break
    tracks = []
    moov = [x for x in top if x[0] == b"moov"]
    if not moov:
        raise Mp4Error("not an MP4: no moov box")
    _, ms, me = moov[0]
    movie_timescale = None
    for typ, s, e in _boxes(data, ms, me):
        if typ == b"mvhd":
            v = data[s]
            movie_timescale = struct.unpack(">I", data[s + 20:s + 24] if v == 1 else data[s + 12:s + 16])[0]
        elif typ == b"trak":
            track = {"handler": None, "codec": None, "coded_width": 0, "coded_height": 0,
                     "sar": {"h": 1, "v": 1}, "mdhd": None}
            for t2, s2, e2 in _boxes(data, s, e):
                if t2 == b"tkhd":
                    track.update(_parse_tkhd(data[s2:e2]))
                elif t2 == b"mdia":
                    for t3, s3, e3 in _boxes(data, s2, e2):
                        if t3 == b"mdhd":
                            track["mdhd"] = _parse_mdhd(data[s3:e3])
                        elif t3 == b"hdlr" and e3 - s3 >= 12:
                            track["handler"] = data[s3 + 8:s3 + 12].decode("latin-1")
                        elif t3 == b"minf":
                            for t4, s4, e4 in _boxes(data, s3, e3):
                                if t4 == b"stbl":
                                    for t5, s5, e5 in _boxes(data, s4, e4):
                                        if t5 == b"stsd":
                                            info = _parse_stsd(data[s5:e5])
                                            if info:
                                                track.update(info)
            tracks.append(track)
    return {"path": path, "brands": brands, "movie_timescale": movie_timescale,
            "tracks": tracks}
