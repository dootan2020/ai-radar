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
import math
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

VERSION = 'nen-3d-2'
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
             wire='#38C8FF', wire_strength=1.5, air_far='#0B2A6B', air_mid='#2D7CE0', air_sun='#FFB070',
             sun_glow=12.0, link_strength=2.2, sunlight='#FFE7C4'),
        dict(name='teal dusk', space='#01070A', nebula_a='#04211F', nebula_b='#0D4A4A', nebula_c='#3AA09A',
             nebula_strength=1.0, ocean='#02070A', land='#0A0D0C', city='#FFD08A', city_strength=8.0,
             wire='#5CFFD6', wire_strength=1.5, air_far='#063A44', air_mid='#1FA3B8', air_sun='#FFC98A',
             sun_glow=12.0, link_strength=2.2, sunlight='#FFF0D6'),
        dict(name='magenta rise', space='#05030A', nebula_a='#1E0A2A', nebula_b='#4A1A5E', nebula_c='#A04A9A',
             nebula_strength=1.0, ocean='#05040A', land='#0D0B10', city='#FFC27A', city_strength=8.0,
             wire='#B07CFF', wire_strength=1.5, air_far='#2A1468', air_mid='#7A4CE0', air_sun='#FF9A7A',
             sun_glow=12.0, link_strength=2.2, sunlight='#FFE0D0'),
    ],
    'data-centre': [
        dict(name='cold aisle', space='#010203', rack='#0D1014', panel='#1A1E24', floor='#0B0D10', led_a='#33D6FF',
             led_b='#5CFF9D', led_strength=9.0, haze='#9FB8D8', shaft='#BFD8FF'),
        dict(name='amber night', space='#020101', rack='#100E0D', panel='#1E1B19', floor='#0D0B0A', led_a='#FFB347',
             led_b='#4FC3FF', led_strength=8.0, haze='#D8B894', shaft='#FFD9A8'),
        dict(name='violet ops', space='#020104', rack='#0F0D16', panel='#1C1926', floor='#0C0A12', led_a='#B57BFF',
             led_b='#FF5FA8', led_strength=8.5, haze='#B4A4D8', shaft='#D8C8FF'),
    ],
    'fibre-optics': [
        dict(name='ice fibre', space='#020308', nebula_a='#081430', nebula_b='#10305A', nebula_c='#2E6FA0',
             nebula_strength=.8, fibre_low='#0A1A30', fibre_high='#4FD8FF', fibre_strength=1.4, tip_a='#9FF0FF',
             tip_b='#E8FBFF'),
        dict(name='sunset fibre', space='#060205', nebula_a='#2A0A1E', nebula_b='#5A1838', nebula_c='#A04A5A',
             nebula_strength=.8, fibre_low='#2A0A18', fibre_high='#FF7A9A', fibre_strength=1.3, tip_a='#FFC07A',
             tip_b='#FF6FB0'),
        dict(name='green signal', space='#010503', nebula_a='#06201A', nebula_b='#0E4432', nebula_c='#3A9A70',
             nebula_strength=.8, fibre_low='#06201A', fibre_high='#6CFFB8', fibre_strength=1.3, tip_a='#C8FFE6',
             tip_b='#6CE4FF'),
    ],
    'projected-polytope': [
        dict(name='chrome dawn', space='#030308', nebula_a='#0E1030', nebula_b='#24285E', nebula_c='#5A5FA8',
             nebula_strength=.8, metal='#D8DCE6', panel='#B8D8FF', film=480, key='#FFE2C4', rim='#7FB8FF'),
        dict(name='gold lattice', space='#050304', nebula_a='#22100A', nebula_b='#4A2A14', nebula_c='#9A6A3A',
             nebula_strength=.7, metal='#E6C27A', panel='#FFE0B0', film=360, key='#FFF0DC', rim='#FF9A5C'),
        dict(name='teal prism', space='#010506', nebula_a='#04201E', nebula_b='#0C4846', nebula_c='#3A9A96',
             nebula_strength=.8, metal='#C8E6E4', panel='#A8FFF0', film=560, key='#E8FFFA', rim='#5CE0FF'),
    ],
    'voxel-terrain': [
        dict(name='blue hour', space='#03050C', sky_mid='#0E1A38', fog='#3A5A8A', fog_strength=.55, low='#0B0F18',
             high='#2A3550', top_low='#1A2238', top_high='#9FB4D8', beacon='#5CE8FF', beacon_strength=9.0,
             sun='#FFB27A'),
        dict(name='ember dusk', space='#070306', sky_mid='#2A0E1A', fog='#8A4A4A', fog_strength=.5, low='#120A0C',
             high='#3A2228', top_low='#2A1418', top_high='#D8A08A', beacon='#FFD27A', beacon_strength=9.0,
             sun='#FF9A5C'),
        dict(name='green grid', space='#020605', sky_mid='#08201A', fog='#2E6A5A', fog_strength=.5, low='#081210',
             high='#1E3A32', top_low='#12241E', top_high='#8AD8B8', beacon='#7CFFC8', beacon_strength=9.0,
             sun='#E8FFD8'),
    ],
}
FAMILIES = list(PALETTES)


def today_bangkok():
    return dt.datetime.now(BANGKOK).date()


def seed_of(*parts):
    return int.from_bytes(hashlib.sha256('/'.join(map(str, (VERSION,) + parts)).encode()).digest()[:8], 'big')


ORDER = FAMILIES[:]
random.Random(seed_of('order')).shuffle(ORDER)


def schedule(day):
    """(family, cycle) for a day, counted from EPOCH.

    No family may appear twice inside any len(FAMILIES) consecutive days. With
    as many days in the window as there are families, the only sequences that
    satisfy this repeat one fixed order, so the order is shuffled once and each
    family keeps its weekday. Variety on a return comes from the parameters:
    every cycle mirrors the composition and changes palette and layout."""
    index = (day - EPOCH).days
    if index < 0:
        raise ValueError(f'dates before {EPOCH} are not scheduled')
    cycle, position = divmod(index, len(FAMILIES))
    return ORDER[position], cycle


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
                 exposure=.8, layout_angle=side * [0, 22, 32][cycle % 3], cross=[0.0, 17.0, 0.0, 21.0][cycle % 4],
                 macro_scale=[1.0, .6, 1.45][(cycle + 1) % 3])
    elif family == 'orbital-horizon':
        p.update(altitude=round(rng.uniform(2.6, 4.2), 3), horizon=round(rng.uniform(.45, .5), 3),
                 roll=round(-side * rng.uniform(2.0, 5.0), 2), sun_azimuth=round(rng.uniform(.3, .42), 3),
                 sun_depth=round(rng.uniform(.13, .18), 3), air=1.6, scale_height=round(rng.uniform(.28, .36), 3),
                 air_glow=round(rng.uniform(.085, .1), 4), satellites=rng.randint(9, 15),
                 links=rng.randint(7, 11))
    elif family == 'data-centre':
        p.update(aisle=round(rng.uniform(.9, 1.2), 3), eye_x=round(rng.uniform(.1, .45), 3),
                 eye_z=round(rng.uniform(1.05, 1.45), 3), look_x=round(rng.uniform(-.2, .5), 3),
                 tilt=round(rng.uniform(.15, .5), 3), lens=[24, 30, 35][cycle % 3],
                 roll=round(rng.uniform(-1.5, 1.5), 2), gap_chance=rng.uniform(.01, .04), fill=rng.uniform(.75, .92),
                 led_mix=rng.uniform(.55, .8), floor_roughness=round(rng.uniform(.18, .32), 3),
                 haze=round(rng.uniform(.05, .08), 4),
                 shafts=[round(rng.uniform(6, 12), 2), round(rng.uniform(17, 24), 2), round(rng.uniform(29, 36), 2)],
                 shaft_energy=rng.uniform(450, 650), focus=round(rng.uniform(4.5, 7.0), 2), samples=192)
    elif family == 'fibre-optics':
        p.update(roll=round(rng.uniform(-3, 3), 2), fibres=rng.randint(700, 900),
                 second_share=[0.0, .45, .3][cycle % 3], base_u=round(rng.uniform(.3, .42), 3),
                 fan_u=round(rng.uniform(.24, .34), 3), fan_v=round(rng.uniform(.68, .8), 3),
                 spread=round(rng.uniform(.08, .12), 3), focus=round(rng.uniform(6.0, 7.0), 2))
    elif family == 'projected-polytope':
        kinds = ['24-cell', '600-cell', '8-cell']
        p.update(polytope=kinds[cycle % 3], echo=kinds[(cycle + 1) % 3] if cycle % 2 == 0 else None,
                 angles=[round(rng.uniform(0, math.tau), 3) for _ in range(5)],
                 echo_angles=[round(rng.uniform(0, math.tau), 3) for _ in range(5)],
                 place_u=round(rng.uniform(.25, .31), 3), place_v=round(rng.uniform(.62, .7), 3),
                 size=round(rng.uniform(1.9, 2.3), 3), roll=round(rng.uniform(-3, 3), 2),
                 panel_opacity=round(rng.uniform(.1, .18), 3), key_energy=rng.uniform(900, 1300), samples=192)
    elif family == 'voxel-terrain':
        p.update(lean=round(rng.uniform(.2, .45), 3), valley=round(rng.uniform(3.0, 5.0), 3),
                 relief=round(rng.uniform(26.0, 32.0), 3), beacons=rng.uniform(.02, .04), beacon_level=6,
                 eye_x=round(rng.uniform(.0, 2.0), 3), eye_z=round(rng.uniform(3.0, 3.8), 3),
                 look_x=round(rng.uniform(-1.0, 1.5), 3), look_z=round(rng.uniform(3.2, 3.8), 3),
                 roll=round(rng.uniform(-2, 2), 2), fog=round(rng.uniform(26, 36), 2), horizon=.55,
                 sun_energy=rng.uniform(2.5, 4.0), focus=round(rng.uniform(16, 22), 2))
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
