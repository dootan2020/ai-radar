"""Copy the published backgrounds from the radar-wallpapers branch into the site.

    python wallpaper/site_restore.py --remote https://github.com/OWNER/REPO.git --site site/nen

Used by the site build. It never fails the build: when the branch is missing,
unreadable or holds anything unexpected, it copies nothing and the page falls
back to its packaged image. Authentication follows radar/story_pages.py: a
GITHUB_TOKEN in the environment becomes an extra header, never part of a URL.
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

BRANCH = 'radar-wallpapers'
REF = f'refs/heads/{BRANCH}'
IMAGE = re.compile(r'\d{4}-\d{2}-\d{2}\.(avif|webp)')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
MAX_FILES = 40


class RestoreError(Exception):
    pass


def git_environment(remote):
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    parsed = urlsplit(remote)
    if parsed.scheme in {'http', 'https'} and (parsed.username or parsed.password):
        raise RestoreError('Remote URLs must not contain credentials')
    token = env.get('GITHUB_TOKEN')
    server = env.get('GITHUB_SERVER_URL', 'https://github.com').rstrip('/')
    if token and remote.startswith(server + '/'):
        count = int(env.get('GIT_CONFIG_COUNT', '0'))
        authorization = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
        env[f'GIT_CONFIG_KEY_{count}'] = f'http.{server}/.extraheader'
        env[f'GIT_CONFIG_VALUE_{count}'] = 'AUTHORIZATION: basic ' + authorization
        env['GIT_CONFIG_COUNT'] = str(count + 1)
    return env


def git(repo, remote, *args, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(repo), *args], env=git_environment(remote), capture_output=True,
                            timeout=120)
    if result.returncode not in allowed:
        raise RestoreError(f'git {args[0]} failed (exit {result.returncode})')
    return result


def validate(paths, lich_text):
    """Check the branch tree and lich.json; return the list of days."""
    if 'lich.json' not in paths:
        raise RestoreError('no lich.json')
    images = set(paths) - {'lich.json'}
    if any(not IMAGE.fullmatch(p) for p in images) or len(images) > MAX_FILES:
        raise RestoreError('unexpected path on the branch')
    lich = json.loads(lich_text)
    days = lich.get('days') if isinstance(lich, dict) else None
    if not isinstance(days, list) or not days:
        raise RestoreError('lich.json has no days')
    for day in days:
        if (not isinstance(day, dict) or not DATE.fullmatch(str(day.get('date', '')))
                or day.get('file') not in images or not str(day['file']).startswith(day['date'])
                or not isinstance(day.get('family'), str) or day.get('w') != 2560 or day.get('h') != 1440):
            raise RestoreError(f'bad lich.json entry {day!r}'[:200])
    return days


def restore(remote, site, workdir):
    """Copy the branch into site; return the number of days, or None when the branch is missing."""
    repo = Path(workdir)
    git(repo, remote, 'init', '--quiet')
    git(repo, remote, 'config', 'core.autocrlf', 'false')
    found = git(repo, remote, 'ls-remote', '--exit-code', '--refs', remote, REF, allowed=(0, 2))
    if found.returncode == 2:
        return None
    lines = found.stdout.decode().splitlines()
    if len(lines) != 1 or lines[0].split()[1:] != [REF]:
        raise RestoreError('unexpected branch lookup result')
    advertised = lines[0].split()[0]
    git(repo, remote, 'fetch', '--quiet', '--no-tags', '--depth', '1', remote, REF)
    commit = git(repo, remote, 'rev-parse', 'FETCH_HEAD').stdout.decode().strip()
    if commit != advertised:
        raise RestoreError('branch changed during restore')
    paths = []
    for record in git(repo, remote, 'ls-tree', '-r', '-z', commit).stdout.decode().split('\0'):
        if record:
            metadata, path = record.split('\t', 1)
            if not metadata.startswith('100644 blob '):
                raise RestoreError('unexpected file type on the branch')
            paths.append(path)
    lich_text = git(repo, remote, 'show', f'{commit}:lich.json').stdout.decode('utf-8') if 'lich.json' in paths else ''
    days = validate(paths, lich_text)
    git(repo, remote, 'checkout', '--quiet', '--detach', commit)
    site = Path(site)
    site.mkdir(parents=True, exist_ok=True)
    for day in days:
        shutil.copyfile(repo / day['file'], site / day['file'])
    (site / 'lich.json').write_text(json.dumps(dict(days=days), ensure_ascii=False, indent=1) + '\n',
                                    encoding='utf-8', newline='\n')
    return len(days)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--remote', required=True)
    parser.add_argument('--site', type=Path, default=Path('site/nen'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='wallpapers-') as workdir:
        try:
            count = restore(args.remote, args.site, workdir)
        except (RestoreError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f'::warning::Daily backgrounds not restored ({exc}); the page uses its packaged image.')
            return 0
    if count is None:
        print(f'No {BRANCH} branch yet; the page uses its packaged image.')
    else:
        print(f'Restored {count} daily backgrounds into {args.site}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
