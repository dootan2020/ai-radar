#!/usr/bin/env python3
"""Build the production Chrome Web Store zip package for Halcyon extension.

Excludes development and build artifacts (README.md, sync-site.py, store folder,
temporary files), keeping only runtime assets required by Manifest V3.
"""
import json
from pathlib import Path
import sys
import zipfile


EXCLUDED_TOP_LEVEL = {'README.md', 'sync-site.py', 'store'}
EXCLUDED_PATTERNS = {'__pycache__', '.DS_Store', 'Thumbs.db'}


def should_include(rel_path: Path) -> bool:
    parts = rel_path.parts
    if not parts:
        return False
    if parts[0] in EXCLUDED_TOP_LEVEL:
        return False
    for part in parts:
        if part in EXCLUDED_PATTERNS or part.endswith('.pyc') or part.endswith('.zip'):
            return False
    return True


def build_store_zip():
    store_dir = Path(__file__).resolve().parent
    ext_dir = store_dir.parent
    root_dir = ext_dir.parent

    manifest_file = ext_dir / 'manifest.json'
    if not manifest_file.is_file():
        print(f"Error: manifest.json not found at {manifest_file}", file=sys.stderr)
        sys.exit(1)

    with manifest_file.open('r', encoding='utf-8') as f:
        manifest = json.load(f)

    version = manifest.get('version', '0.1.0')
    zip_name = f'extension-halcyon-{version}.zip'

    # Store in extension/store/ and also mirror at root for easy access
    store_zip_path = store_dir / zip_name
    root_zip_path = root_dir / zip_name

    included_files = []
    for file_path in sorted(ext_dir.rglob('*')):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(ext_dir)
        if should_include(rel):
            included_files.append((file_path, rel.as_posix()))

    if not included_files:
        print("Error: No files selected to package!", file=sys.stderr)
        sys.exit(1)

    # Write zip file
    with zipfile.ZipFile(store_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for full_path, archive_name in included_files:
            zf.write(full_path, arcname=archive_name)

    # Copy / write to root as well
    if root_zip_path != store_zip_path:
        import shutil
        shutil.copy2(store_zip_path, root_zip_path)

    zip_size = store_zip_path.stat().st_size
    print(f"Built {zip_name} ({zip_size:,} bytes)")
    print(f"Location: {store_zip_path}")
    print(f"Files in zip ({len(included_files)} files):")
    with zipfile.ZipFile(store_zip_path, 'r') as zf:
        for info in zf.infolist():
            print(f"  - {info.filename} ({info.file_size:,} bytes)")

    return 0


if __name__ == '__main__':
    sys.exit(build_store_zip())
