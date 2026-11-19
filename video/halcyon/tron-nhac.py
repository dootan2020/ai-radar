#!/usr/bin/env python3
"""Put the Halcyon channel's music bed under a finished video.

Usage: py -3.12 tron-nhac.py <video.mp4> [--out <path.mp4>]

Writes <name>-nhac.mp4 beside the input (or to --out) and <name>-nhac.json
next to the output. The picture is stream-copied and the voice is only
combined with the bed (no gain, EQ or limiter on the voice). The script
refuses, and writes nothing, when the picture checksum or frame count
differs, the duration moves, the loudness moves more than MAX_LU_SHIFT from
the input, or the true peak rises above MAX_TRUE_PEAK_DBTP. A video longer
than the track's remaining length is an error, never a loop.

Bed: "Voice Over Under" by Kevin MacLeod (incompetech.com), CC BY 4.0.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- constants: the one bed every video gets -------------------------------
HERE = Path(__file__).resolve().parent
# The track is not committed (see README.md): point HALCYON_MUSIC_TRACK at the mp3, or put it at video/halcyon/music/Voice Over Under.mp3 (git-ignored).
TRACK = Path(os.environ["HALCYON_MUSIC_TRACK"]) if os.environ.get("HALCYON_MUSIC_TRACK") else HERE / "music" / "Voice Over Under.mp3"
START_OFFSET_S = 14.222      # first beat of bar 9 at 135 bpm (8 bars x 240 / 135, rounded)
GAIN_DB = -16.0              # puts the filtered bed at about -34 LUFS over a 25 s window
HIGHPASS_HZ = 120
EQ_HZ, EQ_Q, EQ_DB = 2500, 1, -4
FADE_IN_S = 0.15
FADE_OUT_S = 0.40
AAC_KBPS = 192
MAX_LU_SHIFT = 0.3           # output vs input integrated loudness
MAX_TRUE_PEAK_DBTP = -1.0
MAX_DURATION_DRIFT_S = 0.03
BED_TARGET_LUFS = -34.0      # reported; the gain constant above is what is applied
# -----------------------------------------------------------------------------

TZ = timezone(timedelta(hours=7))


class Refusal(Exception):
    pass


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def ffprobe_json(path, *extra):
    rc, out, err = run(["ffprobe", "-v", "error", "-print_format", "json", *extra, str(path)])
    if rc != 0:
        raise Refusal(f"ffprobe failed on {path}: {err.strip()}")
    return json.loads(out)


def video_facts(path):
    info = ffprobe_json(path, "-show_format", "-show_streams", "-count_frames")
    v = [s for s in info["streams"] if s["codec_type"] == "video"]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not v:
        raise Refusal(f"{path} has no video stream")
    if not a:
        raise Refusal(f"{path} has no audio stream (nothing to put a bed under)")
    return {
        "frames": int(v[0]["nb_read_frames"]),
        "duration_s": float(info["format"]["duration"]),
    }


def video_md5(path):
    rc, out, err = run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-c", "copy", "-f", "md5", "-"])
    m = re.search(r"MD5=([0-9a-f]{32})", out)
    if rc != 0 or not m:
        raise Refusal(f"cannot checksum the video stream of {path}: {err.strip()}")
    return m.group(1)


def loudness(args_in, audio_filter=None):
    """Integrated LUFS and true peak (dBTP) of whatever ffmpeg reads from args_in."""
    af = "ebur128=peak=true" if not audio_filter else audio_filter + ",ebur128=peak=true"
    rc, out, err = run(["ffmpeg", "-hide_banner", "-nostats", *args_in, "-vn", "-af", af, "-f", "null", "NUL"])
    summary = err[err.rfind("Summary:"):] if "Summary:" in err else ""
    i = re.search(r"\n\s*I:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    tp = re.search(r"True peak:\s*\n\s*Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    if rc != 0 or not i or not tp:
        raise Refusal(f"cannot measure loudness: {err.strip()[-300:]}")
    return float(i.group(1)), float(tp.group(1))


def bed_filter():
    return (f"highpass=f={HIGHPASS_HZ},equalizer=f={EQ_HZ}:t=q:w={EQ_Q}:g={EQ_DB},"
            f"volume={GAIN_DB:.3f}dB")


def track_length():
    info = ffprobe_json(TRACK, "-show_format")
    return float(info["format"]["duration"])


def main():
    ap = argparse.ArgumentParser(description="Mix the Halcyon music bed under a finished video.")
    ap.add_argument("video")
    ap.add_argument("--out")
    ns = ap.parse_args()

    src = Path(ns.video).resolve()
    if not src.is_file():
        raise Refusal(f"input not found: {src}")
    if not TRACK.is_file():
        raise Refusal(f"track not found: {TRACK}")
    out = Path(ns.out).resolve() if ns.out else src.with_name(src.stem + "-nhac.mp4")
    if out == src:
        raise Refusal("output path equals the input path")
    js = out.with_suffix(".json")
    tmp = out.with_name(out.stem + ".tmp.mp4")

    before = video_facts(src)
    dur = before["duration_s"]
    remaining = track_length() - START_OFFSET_S
    if dur > remaining:
        raise Refusal(f"video is {dur:.3f} s but only {remaining:.3f} s of the track remain after "
                      f"the {START_OFFSET_S} s start; refusing to loop")
    md5_in = video_md5(src)
    in_lufs, in_tp = loudness(["-i", str(src)])

    seek = ["-ss", f"{START_OFFSET_S:.3f}", "-t", f"{dur:.3f}", "-i", str(TRACK)]
    bed_lufs, bed_tp = loudness(seek, bed_filter())

    fo_start = dur - FADE_OUT_S
    fc = (f"[1:a]{bed_filter()},afade=t=in:st=0:d={FADE_IN_S},afade=t=out:st={fo_start:.3f}:d={FADE_OUT_S},"
          f"aformat=sample_rates=48000:channel_layouts=stereo[m];"
          f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[v];"
          f"[v][m]amix=inputs=2:duration=first:normalize=0[a]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", str(src), *seek,
           "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
           "-c:a", "aac", "-b:a", f"{AAC_KBPS}k", "-movflags", "+faststart", "-f", "mp4", str(tmp)]
    try:
        rc, o, e = run(cmd)
        if rc != 0:
            raise Refusal(f"ffmpeg mix failed: {e.strip()[-300:]}")
        after = video_facts(tmp)
        md5_out = video_md5(tmp)
        out_lufs, out_tp = loudness(["-i", str(tmp)])

        problems = []
        if md5_out != md5_in:
            problems.append(f"picture checksum differs ({md5_in} -> {md5_out})")
        if after["frames"] != before["frames"]:
            problems.append(f"frame count differs ({before['frames']} -> {after['frames']})")
        if abs(after["duration_s"] - dur) > MAX_DURATION_DRIFT_S:
            problems.append(f"duration moved ({dur:.3f} -> {after['duration_s']:.3f} s)")
        if abs(out_lufs - in_lufs) > MAX_LU_SHIFT:
            problems.append(f"loudness moved {out_lufs - in_lufs:+.2f} LU "
                            f"({in_lufs:.1f} -> {out_lufs:.1f} LUFS; limit {MAX_LU_SHIFT} LU)")
        if out_tp > MAX_TRUE_PEAK_DBTP:
            problems.append(f"true peak {out_tp:.1f} dBTP is above {MAX_TRUE_PEAK_DBTP} dBTP")
        if problems:
            raise Refusal("; ".join(problems))

        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()

    rec = {
        "made": datetime.now(TZ).isoformat(timespec="seconds"),
        "input": str(src),
        "output": str(out),
        "track": str(TRACK),
        "track_sha256": hashlib.sha256(TRACK.read_bytes()).hexdigest(),
        "start_offset_s": START_OFFSET_S,
        "gain_db": GAIN_DB,
        "filters": {"highpass_hz": HIGHPASS_HZ, "eq": {"hz": EQ_HZ, "q": EQ_Q, "db": EQ_DB},
                    "fade_in_s": FADE_IN_S, "fade_out_s": FADE_OUT_S, "ducking": False},
        "bed_alone_lufs": bed_lufs,
        "bed_target_lufs": BED_TARGET_LUFS,
        "input_lufs": in_lufs, "input_true_peak_dbtp": in_tp,
        "output_lufs": out_lufs, "output_true_peak_dbtp": out_tp,
        "lufs_shift": round(out_lufs - in_lufs, 2),
        "frames_input": before["frames"], "frames_output": after["frames"],
        "duration_input_s": dur, "duration_output_s": after["duration_s"],
        "video_md5_input": md5_in, "video_md5_output": md5_out,
        "voice_processed": False,
    }
    js.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"OK {out}\n   bed {bed_lufs:.1f} LUFS | loudness {in_lufs:.1f} -> {out_lufs:.1f} LUFS "
          f"| true peak {in_tp:.1f} -> {out_tp:.1f} dBTP | frames {after['frames']} | picture identical")


if __name__ == "__main__":
    try:
        main()
    except Refusal as r:
        print(f"REFUSED: {r}", file=sys.stderr)
        sys.exit(2)
