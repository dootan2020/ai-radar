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
# Silent spans (a paragraph with no voice and no subtitle, see MOT-LENH.md): the bed alone at -34 LUFS would read as a broken video, so it is lifted there.
LIFT_DB = 12.0               # the adviser's addition (21/11/2026), not the owner's words: configurable with --lift-db, off when no --silence is given
LIFT_RAMP_S = 0.4            # the lift rises and falls linearly over this long at each edge of a span
LIFT_MARGIN_S = 0.2          # the voice guard leaves this much around a span out of its measure (the ramps and the audio frames)
LIFT_MIN_LUFS, LIFT_MAX_LUFS = -30.0, -16.0   # the lifted bed, measured over the silent spans only: audible, and still quieter than the -15 LUFS voice
NO_VOICE_DBFS = -60.0        # the input may not be louder than this inside a silent span (a heard voice there is a bug in the script or the voice step)
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


def parse_windows(items, dur):
    """['A:B', ...] -> [(a, b)] in seconds, sorted, inside the video and not touching each other."""
    out = []
    for it in items or []:
        try:
            a, b = (float(x) for x in it.split(":"))
        except ValueError:
            raise Refusal(f"--silence {it!r} must read A:B in seconds, for example 96.2:113.2")
        if not 0 <= a < b <= dur + 0.03:
            raise Refusal(f"--silence {it} lies outside the video (0 to {dur:.2f} s) or ends before it starts")
        out.append((a, b))
    out.sort()
    for (a0, b0), (a1, b1) in zip(out, out[1:]):
        if a1 < b0 + 2 * LIFT_RAMP_S:
            raise Refusal(f"silent spans {a0}-{b0} and {a1}-{b1} are closer than two ramps ({2 * LIFT_RAMP_S} s); make them one")
    return out


def lift_filter(windows, lift_db, ramp=LIFT_RAMP_S):
    """The bed's extra gain as one volume expression of time: 1 outside, 10^(db/20) inside each window, linear ramps of `ramp` s on both edges."""
    g = 10 ** (lift_db / 20)
    terms = "+".join(f"max(0,min(1,min((t-{a:.3f})/{ramp},({b:.3f}-t)/{ramp})))" for a, b in windows)
    return f"volume='1+({g:.5f}-1)*({terms})':eval=frame"


def widen(windows, margin, dur):
    """Each span moved outward by `margin` s at both edges (inward when negative), kept inside 0..dur; spans that vanish are dropped."""
    out = [(max(0.0, a - margin), min(dur, b + margin)) for a, b in windows]
    return [(a, b) for a, b in out if b - a > 0.05]


def complement(spans, dur):
    """The parts of 0..dur that are not in `spans` (sorted, not touching)."""
    out, t = [], 0.0
    for a, b in spans:
        if a - t > 0.05:
            out.append((t, a))
        t = max(t, b)
    if dur - t > 0.05:
        out.append((t, dur))
    return out


def span_loudness(src, spans):
    """Integrated LUFS and true peak of only `spans` of the audio of `src`, joined end to end (atrim + concat: aselect does not select by time on audio)."""
    n = len(spans)
    if not n:
        raise Refusal("nothing to measure: the silent spans leave no voiced part, or no silent part")
    cut = ";".join(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[t{i}]" for i, (a, b) in enumerate(spans))
    join = "".join(f"[t{i}]" for i in range(n))
    fc = f"{cut};{join}concat=n={n}:v=0:a=1,ebur128=peak=true[o]"
    rc, out, err = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-filter_complex", fc, "-map", "[o]", "-f", "null", "NUL"])
    summary = err[err.rfind("Summary:"):] if "Summary:" in err else ""
    i = re.search(r"\n\s*I:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    tp = re.search(r"True peak:\s*\n\s*Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    if rc != 0 or not i or not tp:
        raise Refusal(f"cannot measure loudness of the spans: {err.strip()[-300:]}")
    return float(i.group(1)), float(tp.group(1))


def track_length():
    info = ffprobe_json(TRACK, "-show_format")
    return float(info["format"]["duration"])


def main():
    ap = argparse.ArgumentParser(description="Mix the Halcyon music bed under a finished video.")
    ap.add_argument("video")
    ap.add_argument("--out")
    ap.add_argument("--silence", action="append", default=[], metavar="A:B", help="a silent span in seconds (repeatable): the bed is lifted there")
    ap.add_argument("--lift-db", type=float, default=LIFT_DB, help=f"the lift in dB inside --silence spans (default {LIFT_DB:g})")
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
    windows = parse_windows(ns.silence, dur)
    md5_in = video_md5(src)
    # With silent spans the guard compares the voiced part only (the spans are outside it); with none it compares the whole file, exactly as before.
    voiced = complement(widen(windows, LIFT_MARGIN_S, dur), dur) if windows else None
    in_lufs, in_tp = span_loudness(src, voiced) if windows else loudness(["-i", str(src)])
    if windows:
        _, in_inside_tp = span_loudness(src, widen(windows, -LIFT_MARGIN_S, dur))
        if in_inside_tp > NO_VOICE_DBFS:
            raise Refusal(f"the input is {in_inside_tp:.1f} dBFS inside the silent spans (limit {NO_VOICE_DBFS:.0f}): a voice is heard where the script says there is none")

    seek = ["-ss", f"{START_OFFSET_S:.3f}", "-t", f"{dur:.3f}", "-i", str(TRACK)]
    bed_lufs, bed_tp = loudness(seek, bed_filter())

    fo_start = dur - FADE_OUT_S
    lift = f",{lift_filter(windows, ns.lift_db)}" if windows else ""
    fc = (f"[1:a]{bed_filter()}{lift},afade=t=in:st=0:d={FADE_IN_S},afade=t=out:st={fo_start:.3f}:d={FADE_OUT_S},"
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
        lift_lufs = None
        if windows:
            out_lufs, out_tp = span_loudness(tmp, voiced)
            lift_lufs, _ = span_loudness(tmp, widen(windows, -LIFT_RAMP_S, dur))
            _, whole_tp = loudness(["-i", str(tmp)])
            out_tp = max(out_tp, whole_tp)
        else:
            out_lufs, out_tp = loudness(["-i", str(tmp)])

        problems = []
        if windows and not LIFT_MIN_LUFS <= lift_lufs <= LIFT_MAX_LUFS:
            problems.append(f"the lifted bed measures {lift_lufs:.1f} LUFS inside the silent spans (allowed {LIFT_MIN_LUFS:.0f} to {LIFT_MAX_LUFS:.0f}); "
                            f"change --lift-db ({ns.lift_db:g}) or look at the bed")
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
    if windows:
        rec["lift"] = {"db": ns.lift_db, "ramp_s": LIFT_RAMP_S, "spans": [list(w) for w in windows], "lifted_bed_lufs": lift_lufs,
                       "allowed_lufs": [LIFT_MIN_LUFS, LIFT_MAX_LUFS], "voice_guard": "voiced part only (spans and margins left out)"}
    js.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"OK {out}\n   bed {bed_lufs:.1f} LUFS | loudness {in_lufs:.1f} -> {out_lufs:.1f} LUFS "
          f"| true peak {in_tp:.1f} -> {out_tp:.1f} dBTP | frames {after['frames']} | picture identical"
          + (f"\n   lift {ns.lift_db:g} dB in {len(windows)} silent span(s): bed there {lift_lufs:.1f} LUFS" if windows else ""))


if __name__ == "__main__":
    try:
        main()
    except Refusal as r:
        print(f"REFUSED: {r}", file=sys.stderr)
        sys.exit(2)
