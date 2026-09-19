#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyexiftool", "tqdm", "pymysql", "python-dotenv"]
# ///
"""Archive media on WD Elements using PhotoPrism's whole-file SHA-1 index."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile

import exiftool
import pymysql
from dotenv import dotenv_values
from tqdm import tqdm
from archivist import extract_photo_dates, extract_video_date, calculate_target_path

DRIVE = Path('/Volumes/WD Elements AE')
VOLUME_UUID = 'AD5EAD7E-47AE-48A3-B42C-B223BA42063D'
ENV_FILE = Path.home() / 'personal/git/photoprism/.env'
RAW = {'.arw', '.sr2', '.srf', '.raf', '.cr2', '.cr3', '.crw', '.nef', '.nrw',
       '.dng', '.orf', '.rw2', '.pef', '.srw', '.rwl', '.3fr', '.fff', '.iiq', '.mos', '.mrw', '.x3f'}
PHOTOS = RAW | {'.jpg', '.jpeg', '.heic', '.heif', '.png', '.tif', '.tiff'}
VIDEOS = {'.mp4', '.mov'}


def signature(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise RuntimeError(f'Not a regular file: {path}')
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


@dataclass
class Media:
    path: Path
    tree: str
    digest: str
    sig: tuple


def hash_file(path):
    before = signature(path)
    digest = hashlib.sha1()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    if signature(path) != before:
        raise RuntimeError(f'File changed while hashing: {path}')
    return digest.hexdigest(), before


def discover(source):
    found = []
    def fail(error):
        raise error
    for base, dirs, names in os.walk(source, followlinks=False, onerror=fail):
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
        files = [Path(base) / name for name in sorted(names)
                 if not name.startswith('._') and not (Path(base) / name).is_symlink()]
        tree = 'Raws' if any(p.suffix.lower() in RAW for p in files) else 'Export'
        found.extend((p, tree) for p in files if p.suffix.lower() in PHOTOS | VIDEOS and p.is_file())
    return found


def hash_sources(files, threads):
    def work(entry):
        path, tree = entry
        digest, sig = hash_file(path)
        return Media(path, tree, digest, sig)
    with ThreadPoolExecutor(max_workers=threads) as pool:
        return list(tqdm(pool.map(work, files), total=len(files), desc='Hashing sources', unit='file'))


def require_drive():
    if not (DRIVE / 'Raws').is_dir():
        raise RuntimeError(f'WD Elements not mounted: {DRIVE / "Raws"} does not exist')
    result = subprocess.run(['diskutil', 'info', '-plist', str(DRIVE)],
                            capture_output=True, check=True)
    info = plistlib.loads(result.stdout)
    if (info.get('VolumeUUID', '').upper() != VOLUME_UUID or
            info.get('MountPoint') != str(DRIVE) or not os.path.ismount(DRIVE)):
        raise RuntimeError('The expected WD Elements volume is not mounted at its usual path')
    for tree in ('Raws', 'Export'):
        if not (DRIVE / tree).is_dir() or (DRIVE / tree).is_symlink():
            raise RuntimeError(f'Missing or symlinked archive tree: {DRIVE / tree}')


def fetch_index(media, env_file):
    config = dotenv_values(env_file)
    password = config.get('MARIADB_PASSWORD')
    if not password:
        raise RuntimeError(f'MARIADB_PASSWORD missing from {env_file}')
    index = defaultdict(list)
    connection = pymysql.connect(host='127.0.0.1', port=int(config.get('MARIADB_PORT') or 3306),
        user='photoprism', password=password, database='photoprism',
        connect_timeout=10, read_timeout=60, write_timeout=10,
        cursorclass=pymysql.cursors.DictCursor, charset='utf8mb4')
    def decode(value):
        return value.decode('utf-8') if isinstance(value, bytes) else value
    try:
        with connection.cursor() as cursor:
            cursor.execute('START TRANSACTION READ ONLY')
            hashes = sorted({m.digest for m in media})
            for start in range(0, len(hashes), 500):
                batch = hashes[start:start + 500]
                cursor.execute('SELECT file_hash, file_name, file_size FROM files '
                    "WHERE file_root='/' AND file_missing=0 AND deleted_at IS NULL "
                    'AND file_hash IN (' + ','.join(['%s'] * len(batch)) + ')', batch)
                for row in cursor.fetchall():
                    name = PurePosixPath(decode(row['file_name']))
                    if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] not in {'Raws', 'Export', 'Other'}:
                        continue
                    index[decode(row['file_hash'])].append((DRIVE.joinpath(*name.parts), row['file_size']))
    finally:
        connection.rollback()
        connection.close()
    return index


def live_copies(media, index):
    copies = []
    for path, size in index.get(media.digest, []):
        try:
            if (path.resolve().is_relative_to(DRIVE.resolve()) and not path.is_symlink()
                    and size == media.sig[2] and signature(path)[2] == size):
                copies.append(path)
        except FileNotFoundError:
            pass
    return sorted(copies)


def choose_target(path, reserved):
    candidate, number = path, 2
    while candidate in reserved or os.path.lexists(candidate):
        candidate = path.with_name(f'{path.stem}_{number}{path.suffix}')
        number += 1
    reserved.add(candidate)
    return candidate


def unchanged(media):
    if signature(media.path) != media.sig:
        raise RuntimeError(f'Source changed since hashing: {media.path}')


def safe_parent(target):
    relative = target.relative_to(DRIVE)
    current = DRIVE
    for component in relative.parts[:-1]:
        current /= component
        if current.is_symlink():
            raise RuntimeError(f'Symlink in target path: {current}')
        current.mkdir(exist_ok=True)


def copy_verified(media, target):
    """Stage, verify, and publish without overwriting even a concurrent import."""
    unchanged(media)
    safe_parent(target)
    fd, name = tempfile.mkstemp(prefix='.archivist-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output, media.path.open('rb') as source:
            shutil.copyfileobj(source, output, 4 * 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        unchanged(media)
        shutil.copystat(media.path, temporary)
        if hash_file(temporary)[0] != media.digest:
            raise RuntimeError(f'Copy verification failed: {target}')
        # Hard-link publication is atomic and fails if another file appeared.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def delete_indexed(media, copies):
    unchanged(media)
    for copy in copies:
        if os.path.samefile(media.path, copy):
            continue
        digest, sig = hash_file(copy)
        if digest == media.digest:
            unchanged(media)
            if signature(copy) != sig:
                raise RuntimeError(f'Archive copy changed: {copy}')
            media.path.unlink()
            return
    raise RuntimeError(f'No verified archive copy; source retained: {media.path}')


def get_dates(media, batch_size):
    photos = [m.path for m in media if m.path.suffix.lower() in PHOTOS]
    dates = {}
    if photos:
        with exiftool.ExifToolHelper() as et:
            dates.update(extract_photo_dates(photos, et, batch_size))
    for m in media:
        if m.path.suffix.lower() in VIDEOS:
            date = extract_video_date(m.path)
            if date:
                dates[m.path] = date
    return dates


def plan(media, index, dates, mode):
    operations, reserved = [], set()
    for item in media:
        copies = live_copies(item, index)
        if copies:
            operations.append(('delete-source' if mode == 'delete-source' else 'skip-indexed', item, copies))
        elif mode == 'delete-source':
            operations.append(('keep-unindexed', item, None))
        elif item.path not in dates:
            operations.append(('error-no-date', item, None))
        else:
            target = calculate_target_path(item.path, dates[item.path], DRIVE / item.tree, False)
            operations.append((mode, item, choose_target(target, reserved)))
    return operations


def execute(operations, dry_run, guard=require_drive):
    errors = 0
    for action, media, target in operations:
        detail = ', '.join(map(str, target)) if isinstance(target, list) else str(target or '')
        print(f'{"WOULD " if dry_run else ""}{action}: {media.path}' + (f' -> {detail}' if detail else ''))
        if action.startswith('error'):
            errors += 1
        if dry_run or action not in {'copy', 'move', 'delete-source'}:
            continue
        try:
            guard()
            if action == 'delete-source':
                delete_indexed(media, target)
            else:
                copy_verified(media, target)
                if action == 'move':
                    guard()
                    unchanged(media)
                    media.path.unlink()
        except (OSError, RuntimeError) as error:
            errors += 1
            print(f'ERROR: {error}', file=sys.stderr)
    print('Summary:', dict(Counter(op[0] for op in operations)), f'; errors: {errors}')
    return int(bool(errors))


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--copy', action='store_const', dest='mode', const='copy', help='Copy new files (default)')
    modes.add_argument('--move', action='store_const', dest='mode', const='move', help='Copy and verify new files, then remove their sources; indexed files skipped')
    modes.add_argument('--delete-source', action='store_const', dest='mode', const='delete-source', help='Only delete verified indexed duplicates; keep unindexed files')
    parser.set_defaults(mode='copy')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Read-only preview of every action')
    parser.add_argument('--threads', type=positive, default=1, help='Source hashing workers (default: 1)')
    parser.add_argument('--batch-size', type=positive, default=50)
    parser.add_argument('--db-env', type=Path, default=ENV_FILE, help='PhotoPrism .env with database credentials')
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        parser.error('source must be a directory')
    require_drive()
    for tree in ('Raws', 'Export', 'Other'):
        archive = (DRIVE / tree).resolve()
        if source.is_relative_to(archive) or archive.is_relative_to(source):
            parser.error('source and archive trees must not overlap')
    media = hash_sources(discover(source), args.threads)
    if not media:
        print('No supported media found.')
        return 0
    index = fetch_index(media, args.db_env.expanduser())
    new = [m for m in media if not live_copies(m, index)]
    dates = get_dates(new, args.batch_size) if args.mode != 'delete-source' else {}
    return execute(plan(media, index, dates, args.mode), args.dry_run)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, pymysql.MySQLError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
