"""Publish verified backgrounds to the radar-wallpapers branch of origin.

    python wallpaper/publish.py              # verify, then force-push one orphan commit
    python wallpaper/publish.py --dry-run    # verify and stage only

Run after `daily.py --ahead 14`. The branch holds only the web files and
lich.json ({"days": [{"date", "file", "family", "w", "h"}]}), never PNGs and
never anything else. It keeps the past BACK days and the next AHEAD days
(today included); older days drop out because every publish is a fresh orphan
commit. Every selected day must pass verification (PNG and web file exist,
match the manifest's sha256 and the expected size) and every day from today
to today + AHEAD - 1 must be present; otherwise nothing is pushed and the
site keeps the last good set.
"""
import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily  # noqa: E402

BRANCH = 'radar-wallpapers'
BACK = 7
AHEAD = 14
MIN_WEB_BYTES = 8_000
MAX_WEB_BYTES = 2_000_000


class PublishError(Exception):
    pass


def verify(entry, out):
    """Problems with one manifest entry; an empty list means it may be published."""
    problems = []
    size = (daily.WIDTH, daily.HEIGHT)
    if (entry.get('width'), entry.get('height')) != size:
        problems.append(f'manifest size {entry.get("width")}x{entry.get("height")}')
    png = out / entry.get('png', '')
    if not entry.get('png') or not png.is_file():
        problems.append('PNG missing')
    else:
        if daily.sha256(png) != entry.get('sha256'):
            problems.append('PNG sha256 differs from manifest')
        with Image.open(png) as image:
            if image.size != size:
                problems.append(f'PNG is {image.size}')
    web = out / entry.get('web', '')
    if not entry.get('web') or not web.is_file():
        problems.append('web file missing')
        return problems
    if entry.get('web_settings') != daily.WEB:
        problems.append('web file not encoded with current settings')
    if not MIN_WEB_BYTES <= web.stat().st_size <= MAX_WEB_BYTES:
        problems.append(f'web file is {web.stat().st_size} bytes')
    if daily.sha256(web) != entry.get('web_sha256'):
        problems.append('web sha256 differs from manifest')
    try:
        with Image.open(web) as image:
            image.load()
            if image.size != size:
                problems.append(f'web file decodes at {image.size}')
    except Exception as exc:  # noqa: BLE001 - any decode failure blocks publishing
        problems.append(f'web file does not decode: {exc}')
    return problems


def plan(manifest, out, today, back=BACK, ahead=AHEAD):
    """Return (lich, files) for the window or raise PublishError listing every problem."""
    first, last = today - dt.timedelta(days=back), today + dt.timedelta(days=ahead - 1)
    entries = {e['date']: e for e in manifest.get('wallpapers', [])}
    problems = []
    for k in range(ahead):
        day = (today + dt.timedelta(days=k)).isoformat()
        if day not in entries:
            problems.append(f'{day}: not rendered')
    chosen = [entries[d] for d in sorted(entries) if first.isoformat() <= d <= last.isoformat()]
    for entry in chosen:
        problems += [f'{entry["date"]}: {p}' for p in verify(entry, out)]
    if problems:
        raise PublishError('; '.join(problems))
    days, files = [], {}
    for entry in chosen:
        name = f'{entry["date"]}.{daily.WEB["ext"]}'
        days.append(dict(date=entry['date'], file=name, family=entry['family'], w=entry['width'], h=entry['height']))
        files[name] = out / entry['web']
    return dict(days=days), files


def stage(lich, files, directory):
    directory.mkdir(parents=True, exist_ok=False)
    for name, source in files.items():
        shutil.copyfile(source, directory / name)
    (directory / 'lich.json').write_text(json.dumps(lich, ensure_ascii=False, indent=1) + '\n', encoding='utf-8',
                                         newline='\n')


def git(directory, *args):
    result = subprocess.run(['git', '-C', str(directory), *args], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise PublishError(f'git {args[0]} failed: {result.stderr.strip()[-400:]}')
    return result.stdout.strip()


def push(directory, remote, branch=BRANCH, author=('Halcyon wallpaper', 'wallpaper@localhost')):
    """Commit the staged directory as a single orphan commit and force it onto branch."""
    git(directory, 'init', '--quiet')
    git(directory, 'config', 'core.autocrlf', 'false')
    git(directory, 'config', 'user.name', author[0])
    git(directory, 'config', 'user.email', author[1])
    git(directory, 'checkout', '--quiet', '--orphan', branch)
    git(directory, 'add', '--all')
    days = json.loads((directory / 'lich.json').read_text(encoding='utf-8'))['days']
    git(directory, 'commit', '--quiet', '-m', f'Publish backgrounds {days[0]["date"]} to {days[-1]["date"]}')
    commit = git(directory, 'rev-parse', 'HEAD')
    git(directory, 'push', '--quiet', '--force', remote, f'HEAD:refs/heads/{branch}')
    advertised = git(directory, 'ls-remote', remote, f'refs/heads/{branch}').split()
    if not advertised or advertised[0] != commit:
        raise PublishError(f'remote {branch} is {advertised[:1]}, expected {commit}')
    return commit


def repository_identity(repo):
    def value(key):
        result = subprocess.run(['git', '-C', str(repo), 'config', key], capture_output=True, text=True)
        return result.stdout.strip()
    return value('user.name') or 'Halcyon wallpaper', value('user.email') or 'wallpaper@localhost'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--date', type=dt.date.fromisoformat, default=None, help='today (default: Bangkok)')
    parser.add_argument('--out', type=Path, default=daily.ROOT / 'out')
    parser.add_argument('--remote', default=None, help='default: the origin URL of this repository')
    parser.add_argument('--branch', default=BRANCH)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    today = args.date or daily.today_bangkok()
    repo = daily.ROOT.parent
    manifest = json.loads((args.out / 'manifest.json').read_text(encoding='utf-8'))
    try:
        lich, files = plan(manifest, args.out, today)
    except PublishError as exc:
        print(f'PUBLISH REFUSED, branch left as it was: {exc}', flush=True)
        return 2
    staging = Path(tempfile.mkdtemp(prefix='publish-', dir=daily.ROOT / 'tmp')) / 'site'
    stage(lich, files, staging)
    total = sum(f.stat().st_size for f in staging.iterdir())
    print(f'STAGED {len(files)} days, {total} bytes: {lich["days"][0]["date"]} .. {lich["days"][-1]["date"]}')
    if args.dry_run:
        return 0
    remote = args.remote or git(repo, 'remote', 'get-url', 'origin')
    try:
        commit = push(staging, remote, args.branch, repository_identity(repo))
    except PublishError as exc:
        print(f'PUSH FAILED, branch left as it was: {exc}', flush=True)
        return 3
    finally:
        shutil.rmtree(staging.parent, ignore_errors=True)
    print(f'PUBLISHED {commit} to {args.branch}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
