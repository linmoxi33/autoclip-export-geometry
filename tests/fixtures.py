"""Build structurally valid ISO-BMFF files with controlled geometry.

Only the boxes the auditor reads are populated; mdat carries a few bytes.
"""
import struct

VIDEO_CODECS = {"avc1", "hvc1"}


def box(typ, payload=b""):
    return struct.pack(">I", 8 + len(payload)) + typ.encode("latin-1") + payload


def full(typ, version, flags, payload=b""):
    return box(typ, struct.pack(">B", version) + struct.pack(">I", flags)[1:] + payload)


def matrix(rot):
    if rot == 90:
        m = (0, 0x10000, 0, -0x10000, 0, 0, 0, 0, 0x40000000)
    elif rot == 180:
        m = (-0x10000, 0, 0, 0, -0x10000, 0, 0, 0, 0x40000000)
    elif rot == 270:
        m = (0, -0x10000, 0, 0x10000, 0, 0, 0, 0, 0x40000000)
    else:
        m = (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    return b"".join(struct.pack(">i", v) for v in m)


def avc1(width, height, sar=None, codec="avc1"):
    payload = b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 16
    payload += struct.pack(">HH", width, height)
    payload += struct.pack(">II", 0x00480000, 0x00480000) + struct.pack(">I", 0)
    payload += struct.pack(">H", 1) + b"\x00" * 32 + struct.pack(">H", 0x18) + struct.pack(">h", -1)
    if sar and sar != (1, 1):
        payload += box("pasp", struct.pack(">II", sar[0], sar[1]))
    return box(codec, payload)


def mp4a():
    payload = b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 16
    payload += struct.pack(">HH", 2, 16) + struct.pack(">HH", 0, 0) + struct.pack(">I", 48000)
    return box("mp4a", payload)


def track(track_id, handler, stsd_entry, width, height, rotation=0, seconds=1.5, timescale=1000):
    tkhd = full("tkhd", 0, 3, struct.pack(">IIII", 0, 0, track_id, 0)
                + struct.pack(">I", int(seconds * timescale))
                + b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0) + matrix(rotation)
                + struct.pack(">II", int(width * 65536), int(height * 65536)))
    mdhd = full("mdhd", 0, 0, struct.pack(">IIII", 0, 0, timescale, int(seconds * timescale))
                + struct.pack(">HH", 0x55C4, 0))
    hdlr = full("hdlr", 0, 0, b"\x00" * 4 + handler.encode("latin-1") + b"\x00" * 12 + b"h\x00")
    stsd = full("stsd", 0, 0, struct.pack(">I", 1) + stsd_entry)
    stbl = box("stbl", stsd + full("stts", 0, 0, struct.pack(">I", 0))
               + full("stsc", 0, 0, struct.pack(">I", 0))
               + full("stsz", 0, 0, struct.pack(">II", 0, 0))
               + full("stco", 0, 0, struct.pack(">I", 0)))
    minf = box("minf", full("vmhd", 0, 1, b"\x00" * 8) + stbl)
    return box("trak", tkhd + box("mdia", mdhd + hdlr + minf))


def write_mp4(path, width, height, rotation=0, sar=None, audio=False, codec="avc1", seconds=1.5):
    ftyp = box("ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd = full("mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, int(seconds * 1000))
                + struct.pack(">i", 0x10000) + struct.pack(">h", 0x0100) + b"\x00" * 10
                + matrix(0) + b"\x00" * 24 + struct.pack(">I", 3))
    traks = track(1, "vide", avc1(width, height, sar=sar, codec=codec), width, height, rotation, seconds)
    if audio:
        traks += track(2, "soun", mp4a(), 0, 0, 0, seconds)
    moov = box("moov", mvhd + traks)
    with open(path, "wb") as fh:
        fh.write(ftyp + box("mdat", b"\x00" * 64) + moov)
    return path
