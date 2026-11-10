"""Render Halcyon's daily 3D background on this machine's GPU.

    python wallpaper/daily.py                      # today (Asia/Bangkok)
    python wallpaper/daily.py --date 2026-11-12    # one given day
    python wallpaper/daily.py --ahead 14           # today and the next 13 days
    python wallpaper/daily.py --date 2026-11-12 --family silicon-die --preview 25 --out wallpaper/tmp/look

The date picks a scene family and its parameters deterministically. Families
rotate in shuffled cycles, so none repeats inside its window, and each return
flips the composition side and changes palette. Output lands in wallpaper/out/
(git-ignored): halcyon-<date>.png (original), halcyon-<date>.webp (web) and
manifest.json. A render whose signature and checksum still match is reused.
Needs Blender 4.3 (BLENDER env var, PATH, or the default install) and Pillow.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

VERSION = 'nen-3d-1'
ROOT = Path(__file__).resolve().parent
SCENES = ROOT / 'scenes.py'
BANGKOK = dt.timezone(dt.timedelta(hours=7))  # no daylight saving
EPOCH = dt.date(2026, 11, 9)
WIDTH, HEIGHT = 2560, 1440
WEBP_QUALITY = 82
RENDER_TIMEOUT = 900

PALETTES = {
    'neural-constellation': [
        dict(name='cyan synapse', space='#04060D', nebula_a='#0B1E3A', nebula_b='#13506B', nebula_c='#3FA7B8',
             nebula_strength=1.4, link_a='#2FD3FF', link_b='#7A6CFF', node_a='#9FF4FF', node_b='#5C8CFF',
             node_c='#E9F7FF'),
        dict(name='violet cortex', space='#06040C', nebula_a='#1D0D33', nebula_b='#4B1F6E', nebula_c='#B0549E',
             nebula_strength=1.3, link_a='#B88CFF', link_b='#FF7AC8', node_a='#E2C9FF', node_b='#FF9BD6',
             node_c='#FFFFFF'),
        dict(name='aurora lattice', space='#03080A', nebula_a='#06261F', nebula_b='#0F5A4A', nebula_c='#5CC9A0',
             nebula_strength=1.3, link_a='#4DFFC3', link_b='#38B6FF', node_a='#C8FFEA', node_b='#7FE0FF',
             node_c='#FFFFFF'),
    ],
    'silicon-die': [
        dict(name='copper dusk', space='#020203', substrate='#0B0F1A', cell_a='#1A2236', cell_b='#2B2340',
             macro='#141A2A', metal='#C9864F', via='#E3B56A', data='#38E1FF', data_strength=6.0, film=420,
             key='#FFB676', fill='#6FA8FF'),
        dict(name='cold gold', space='#010204', substrate='#090C12', cell_a='#16202A', cell_b='#1C2B33',
             macro='#10161D', metal='#D9B26A', via='#F1D58C', data='#7CFFB2', data_strength=5.0, film=520,
             key='#DCE9FF', fill='#FFB27A'),
        dict(name='indigo silver', space='#020206', substrate='#0A0A18', cell_a='#1C1A3A', cell_b='#262046',
             macro='#13122A', metal='#B8C2D6', via='#E6ECF5', data='#FF6FD8', data_strength=5.5, film=360,
             key='#B9C8FF', fill='#FF9D6B'),
    ],
    'orbital-horizon': [
        dict(name='blue dawn', space='#020309', nebula_a='#0A1430', nebula_b='#1C2E66', nebula_c='#5B6FB8',
             nebula_strength=1.0, ocean='#03060C', land='#0B0D10', city='#FFB866', city_strength=8.0,
             wire='#38C8FF', wire_strength=.55, air_far='#0B2A6B', air_mid='#2D7CE0', air_sun='#FFB070',
             sun_glow=12.0, sunlight='#FFE7C4'),
        dict(name='teal dusk', space='#01070A', nebula_a='#04211F', nebula_b='#0D4A4A', nebula_c='#3AA09A',
             nebula_strength=1.0, ocean='#02070A', land='#0A0D0C', city='#FFD08A', city_strength=8.0,
             wire='#5CFFD6', wire_strength=.5, air_far='#063A44', air_mid='#1FA3B8', air_sun='#FFC98A',
             sun_glow=12.0, sunlight='#FFF0D6'),
        dict(name='magenta rise', space='#05030A', nebula_a='#1E0A2A', nebula_b='#4A1A5E', nebula_c='#A04A9A',
             nebula_strength=1.0, ocean='#05040A', land='#0D0B10', city='#FFC27A', city_strength=8.0,
             wire='#B07CFF', wire_strength=.5, air_far='#2A1468', air_mid='#7A4CE0', air_sun='#FF9A7A',
             sun_glow=12.0, sunlight='#FFE0D0'),
    ],
}
FAMILIES = list(PALETTES)


def today_bangkok():
    return dt.datetime.now(BANGKOK).date()


def seed_of(*parts):
    return int.from_bytes(hashlib.sha256('/'.join(map(str, (VERSION,) + parts)).encode()).digest()[:8], 'big')


def cycle_order(cycle):
    """Family order of one cycle. Every family appears once per cycle of
    len(FAMILIES) days. A cycle's first GAP families are kept out of the previous
    cycle's last GAP, so no family returns within GAP + 1 days (two days with
    three families, more as families are added). Built forward from the epoch,
    so the answer never depends on what was rendered before."""
    gap = len(FAMILIES) // 2
    order = []
    for k in range(cycle + 1):
        tail = set(order[len(order) - gap:])
        order = FAMILIES[:]
        random.Random(seed_of('cycle', k)).shuffle(order)
        order = [f for f in order if f not in tail] + [f for f in order if f in tail]
    return order


def schedule(day):
    """(family, cycle) for a day, counted from EPOCH."""
    index = (day - EPOCH).days
    if index < 0:
        raise ValueError(f'dates before {EPOCH} are not scheduled')
    cycle, position = divmod(index, len(FAMILIES))
    return cycle_order(cycle)[position], cycle


def params_for(day, family=None):
    scheduled, cycle = schedule(day)
    family = family or scheduled
    seed = seed_of(day.isoformat(), family)
    rng = random.Random(seed)
    palettes = PALETTES[family]
    palette = palettes[(cycle + FAMILIES.index(family)) % len(palettes)]
    side = 1 if (cycle + FAMILIES.index(family)) % 2 == 0 else -1  # each return mirrors the composition
    p = dict(version=VERSION, date=day.isoformat(), family=family, cycle=cycle, seed=seed, palette=palette,
             side=side, bias=side * rng.uniform(.25, .45), seed_offset=round(rng.uniform(0, 1000), 3),
             width=WIDTH, height=HEIGHT, samples=160, look='AgX - Base Contrast', exposure=0.0)
    if family == 'neural-constellation':
        p.update(count=rng.randint(200, 250), reach=rng.uniform(5.0, 6.5), hubs=rng.randint(4, 7),
                 pitch=round(rng.uniform(-.4, .6), 3), roll=round(rng.uniform(-4, 4), 2), exposure=-.2)
    elif family == 'silicon-die':
        p.update(channel=round(rng.uniform(1.5, 2.3), 3), macros=rng.randint(14, 22), traces=rng.randint(2600, 3600),
                 data_share=rng.uniform(.035, .06), camera_height=round(rng.uniform(3.2, 3.7), 3),
                 camera_x=round(side * rng.uniform(.0, .6), 3), roll=round(rng.uniform(-3, 3), 2),
                 key_energy=rng.uniform(11000, 14000), fstop=round(rng.uniform(.28, .4), 3), samples=128,
                 exposure=.8)
    elif family == 'orbital-horizon':
        p.update(altitude=round(rng.uniform(2.6, 4.2), 3), horizon=round(rng.uniform(.45, .5), 3),
                 roll=round(-side * rng.uniform(2.0, 5.0), 2), sun_azimuth=round(rng.uniform(.3, .42), 3),
                 sun_depth=round(rng.uniform(.13, .18), 3), air=1.6, scale_height=round(rng.uniform(.28, .36), 3),
                 air_glow=round(rng.uniform(.085, .1), 4), satellites=rng.randint(9, 15))
    return p


def blender_path():
    candidates = [os.environ.get('BLENDER'), shutil.which('blender'),
                  str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Blender/blender-4.3.2-windows-x64/blender.exe')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise SystemExit('Blender not found: set BLENDER or add it to PATH.')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signature_for(p, blender_version):
    payload = json.dumps(dict(parameters=p, scenes=sha256(SCENES), driver=sha256(__file__), blender=blender_version,
                              webp_quality=WEBP_QUALITY), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def blender_version(blender):
    out = subprocess.run([blender, '--version'], capture_output=True, text=True, timeout=120).stdout
    return out.splitlines()[0].strip() if out else 'unknown'


def luminance_report(image):
    """Calm/readability numbers the coordinator can compare between renders."""
    grey = image.convert('L')
    w, h = grey.size
    histogram = grey.histogram()
    total = w * h
    clipped = sum(histogram[250:]) / total

    def mean(box):
        region = grey.crop(box)
        hist = region.histogram()
        return round(sum(i * c for i, c in enumerate(hist)) / max(1, sum(hist)), 1)

    return dict(clipped_share=round(clipped, 5), mean_all=mean((0, 0, w, h)),
                mean_search_band=mean((int(w * .3), int(h * .2), int(w * .7), int(h * .45))),
                mean_lower_half=mean((0, h // 2, w, h)),
                mean_upper_sides=round((mean((0, 0, w // 3, h // 2)) + mean((2 * w // 3, 0, w, h // 2))) / 2, 1))


def atomic_json(path, data):
    pending = path.with_suffix('.pending.json')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    os.replace(pending, path)


def render_day(day, args, blender, version, manifest, entries):
    p = params_for(day, args.family)
    if args.preview:
        p['width'], p['height'] = WIDTH * args.preview // 100, HEIGHT * args.preview // 100
        p['samples'] = max(32, p['samples'] // 3)
    signature = signature_for(p, version)
    png = args.out / f'halcyon-{day.isoformat()}.png'
    webp = png.with_suffix('.webp')
    prior = entries.get(day.isoformat())
    if (not args.force and prior and prior.get('signature') == signature and png.exists() and webp.exists()
            and sha256(png) == prior.get('sha256')):
        print(f'REUSED {png.name} ({p["family"]}); signature and checksum match', flush=True)
        return prior
    tmp = ROOT / 'tmp'
    tmp.mkdir(exist_ok=True)
    params_file = tmp / f'params-{day.isoformat()}.json'
    result_file = tmp / f'result-{day.isoformat()}.json'
    pending = args.out / f'halcyon-{day.isoformat()}.pending.png'
    for stale in (result_file, pending):
        stale.unlink(missing_ok=True)
    params_file.write_text(json.dumps(p, indent=2), encoding='utf-8', newline='\n')
    env = dict(os.environ, TEMP=str(tmp), TMP=str(tmp))
    started = time.perf_counter()
    command = [blender, '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(SCENES),
               '--', str(params_file), str(pending), str(result_file)]
    run = subprocess.run(command, capture_output=True, text=True, env=env, timeout=RENDER_TIMEOUT)
    if run.returncode != 0 or not result_file.exists() or not pending.exists():
        sys.stderr.write(run.stdout[-4000:] + run.stderr[-4000:])
        raise SystemExit(f'Render failed for {day} (exit {run.returncode}); previous files are untouched.')
    result = json.loads(result_file.read_text(encoding='utf-8'))
    with Image.open(pending) as image:
        image.load()
        if image.size != (p['width'], p['height']):
            raise SystemExit(f'Unexpected size {image.size} for {day}')
        report = luminance_report(image)
        pending_webp = webp.with_name(webp.stem + '.pending.webp')
        image.convert('RGB').save(pending_webp, 'WEBP', quality=WEBP_QUALITY, method=6)
    os.replace(pending, png)
    os.replace(pending_webp, webp)
    record = dict(date=day.isoformat(), family=p['family'], palette=p['palette']['name'], side=p['side'],
                  cycle=p['cycle'], seed=str(p['seed']), version=VERSION, signature=signature,
                  png=png.name, webp=webp.name, width=p['width'], height=p['height'],
                  png_bytes=png.stat().st_size, webp_bytes=webp.stat().st_size, sha256=sha256(png),
                  webp_sha256=sha256(webp), device=result['device'], render_seconds=result['render_seconds'],
                  total_seconds=round(time.perf_counter() - started, 2), samples=p['samples'],
                  blender=result['blender'], luminance=report, scene_stats=result['scene_stats'],
                  rendered_at=dt.datetime.now(BANGKOK).isoformat(timespec='seconds'))
    entries[record['date']] = record
    manifest['wallpapers'] = sorted(entries.values(), key=lambda item: item['date'])
    manifest['latest'] = max(entries)
    atomic_json(args.out / 'manifest.json', manifest)
    print('RENDERED ' + json.dumps({k: record[k] for k in ('date', 'family', 'palette', 'render_seconds',
                                                          'webp_bytes', 'device', 'luminance')}), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--date', type=dt.date.fromisoformat, default=None, help='first day (default: today, Bangkok)')
    parser.add_argument('--ahead', type=int, default=1, help='number of days to render from --date (render-ahead: 14)')
    parser.add_argument('--family', choices=FAMILIES, help='override the scheduled family (for previews)')
    parser.add_argument('--preview', type=int, choices=range(10, 100), metavar='PERCENT',
                        help='render smaller and with fewer samples, for looking only')
    parser.add_argument('--force', action='store_true', help='render even when a matching file exists')
    parser.add_argument('--out', type=Path, default=ROOT / 'out')
    parser.add_argument('--plan', action='store_true', help='print the schedule without rendering')
    args = parser.parse_args()
    if not 1 <= args.ahead <= 60:
        parser.error('--ahead must be between 1 and 60')
    first = args.date or today_bangkok()
    days = [first + dt.timedelta(days=k) for k in range(args.ahead)]
    if args.plan:
        for day in days:
            p = params_for(day, args.family)
            print(day.isoformat(), p['family'], p['palette']['name'], 'side', p['side'])
        return
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / 'manifest.json'
    manifest = (json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists()
                else dict(version=VERSION, timezone='Asia/Bangkok', wallpapers=[]))
    entries = {item['date']: item for item in manifest['wallpapers']}
    blender = blender_path()
    version = blender_version(blender)
    for day in days:
        render_day(day, args, blender, version, manifest, entries)
    print('DONE', len(days), 'day(s) in', args.out, flush=True)


if __name__ == '__main__':
    main()
