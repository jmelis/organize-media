#!/usr/bin/env uv run
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "pyexiftool",
#   "tqdm",
# ]
# ///

"""
Organize media files by date into YYYY/YYYY-MM-DD directory structure.
Extracts dates from EXIF metadata (photos) or creation time (videos).
"""

import argparse
import filecmp
import os
import re
import shutil
import stat
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import exiftool
from tqdm import tqdm

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".arw", ".sr2", ".raf"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
ALL_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS


def discover_files(source_dir: Path) -> Tuple[List[Path], List[Path]]:
    """
    Discover media files in source directory.
    Returns (photo_files, video_files).
    """
    photos = []
    videos = []

    for file_path in source_dir.rglob("*"):
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        if ext in PHOTO_EXTENSIONS:
            photos.append(file_path)
        elif ext in VIDEO_EXTENSIONS:
            videos.append(file_path)

    return photos, videos


def check_immutable_flags(files: List[Path], sample_size: int = 100) -> bool:
    """
    Check if any files have the immutable flag set (macOS 'uchg' flag).
    Samples files for performance on large datasets.
    Returns True if immutable flags found.
    """
    # Sample files to check (all files if small dataset)
    files_to_check = files if len(files) <= 1000 else files[:sample_size]

    # Check for UF_IMMUTABLE (user immutable) or SF_IMMUTABLE (system immutable)
    immutable_flags = 0
    if hasattr(stat, 'UF_IMMUTABLE'):
        immutable_flags |= stat.UF_IMMUTABLE
    if hasattr(stat, 'SF_IMMUTABLE'):
        immutable_flags |= stat.SF_IMMUTABLE

    if immutable_flags == 0:
        # Not on macOS or flags not available
        return False

    for file_path in files_to_check:
        try:
            file_stat = os.stat(file_path)
            if hasattr(file_stat, 'st_flags') and (file_stat.st_flags & immutable_flags):
                return True
        except (OSError, AttributeError):
            # Skip files we can't stat
            continue

    return False


def extract_photo_dates(
    files: List[Path],
    et: exiftool.ExifToolHelper,
    batch_size: int = 50
) -> Dict[Path, datetime]:
    """
    Extract DateTimeOriginal from photo files using batched ExifTool calls.
    Displays progress using tqdm progress bar.
    Returns dict mapping file path to datetime.

    Args:
        files: List of photo file paths
        et: ExifToolHelper instance
        batch_size: Number of photos to process per batch (default 50)
    """
    if not files:
        return {}

    tag = "EXIF:DateTimeOriginal"
    results = {}
    total = len(files)

    try:
        # Process in batches to show progress
        with tqdm(total=total, desc="Extracting EXIF", unit="photo") as pbar:
            for i in range(0, total, batch_size):
                batch = files[i:i + batch_size]
                batch_end = min(i + batch_size, total)

                metadata_list = et.get_tags(batch, tags=tag)

                for file_path, metadata in zip(batch, metadata_list):
                    try:
                        date_str = metadata[tag]

                        if not re.match(r"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}", date_str):
                            raise ValueError(f"Unexpected date format: {date_str}")

                        results[file_path] = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                    except KeyError:
                        # File doesn't have EXIF:DateTimeOriginal
                        pass

                # Update progress bar after each batch
                pbar.update(len(batch))
    except Exception as e:
        # If batch processing fails entirely, we'll report it
        raise RuntimeError(f"Failed to extract EXIF data: {e}")

    return results


def extract_video_date(file_path: Path) -> Optional[datetime]:
    """
    Extract creation time from video file using ffmpeg.
    Returns datetime or None if not found.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(file_path), "-dump"],
            capture_output=True,
            text=True,
            check=False
        )

        for line in result.stderr.split("\n"):
            if "creation_time" in line:
                date_str = line.split()[-1]
                return datetime.fromisoformat(date_str)
    except Exception:
        pass

    return None


def calculate_target_path(
    file_path: Path,
    date: datetime,
    target_dir: Path,
    group_by_extension: bool
) -> Path:
    """
    Calculate the target path for a file based on its date.
    Format: TARGET/YYYY/YYYY-MM-DD/[ext/]filename
    """
    year = date.strftime("%Y")
    day = date.strftime("%Y-%m-%d")

    target = target_dir / year / day

    if group_by_extension:
        ext = file_path.suffix[1:]  # Remove leading dot
        target = target / ext

    return target / file_path.name


def check_file_conflict(source: Path, target: Path) -> Optional[str]:
    """
    Check if moving source to target would cause a conflict.
    Returns error message if conflict exists, None otherwise.
    """
    if target.parent.is_file():
        return f"Target directory {target.parent} is a file"

    if target.exists():
        if filecmp.cmp(source, target, shallow=False):
            return None  # Files are identical, this is fine
        else:
            return f"Target {target} exists with different contents"

    return None


def organize_media(
    source_dir: Path,
    target_dir: Path,
    group_by_extension: bool = False,
    dry_run: bool = False,
    batch_size: int = 50,
    skip_flag_check: bool = False
) -> int:
    """
    Main organizing logic.
    Returns number of errors encountered.

    Args:
        source_dir: Source directory containing media files
        target_dir: Target directory for organized files
        group_by_extension: Whether to group files by extension
        dry_run: Show what would be done without moving files
        batch_size: Number of photos to process per batch for progress updates
        skip_flag_check: Skip checking for immutable flags on source files
    """
    if not source_dir.is_dir():
        print(f"Error: Source '{source_dir}' is not a directory", file=sys.stderr)
        return 1

    if not target_dir.is_dir():
        print(f"Error: Target '{target_dir}' is not a directory", file=sys.stderr)
        return 1

    print(f"Discovering files in {source_dir}...")
    photos, videos = discover_files(source_dir)
    print(f"Found {len(photos)} photos, {len(videos)} videos")

    # Check for immutable flags before processing
    if not skip_flag_check:
        all_files = photos + videos
        if all_files and check_immutable_flags(all_files):
            print(f"\n⚠️  Warning: Found files with immutable flags (uchg)")
            print(f"These files cannot be moved until flags are removed.")
            print(f"\nTo fix, run:")
            print(f"  sudo chflags -R nouchg {source_dir}")
            print()
            response = input("Continue anyway? [y/N]: ").strip().lower()
            if response not in ('y', 'yes'):
                print("Aborted.")
                return 0

    # Extract dates from all media files
    file_dates: Dict[Path, datetime] = {}
    errors: List[Tuple[Path, str]] = []

    # Process photos in batch
    if photos:
        try:
            with exiftool.ExifToolHelper() as et:
                photo_dates = extract_photo_dates(photos, et, batch_size)
                file_dates.update(photo_dates)

                # Track photos that failed
                for photo in photos:
                    if photo not in photo_dates:
                        errors.append((photo, "No EXIF:DateTimeOriginal found"))
        except Exception as e:
            print(f"Error processing photos: {e}", file=sys.stderr)
            return 1

    # Process videos individually (ffmpeg doesn't batch well)
    if videos:
        for video in tqdm(videos, desc="Processing videos", unit="video"):
            date = extract_video_date(video)
            if date:
                file_dates[video] = date
            else:
                errors.append((video, "No creation_time found"))

    # Plan all moves
    moves: List[Tuple[Path, Path]] = []
    duplicates: List[Tuple[Path, Path]] = []

    for file_path, date in file_dates.items():
        target_path = calculate_target_path(file_path, date, target_dir, group_by_extension)

        conflict = check_file_conflict(file_path, target_path)
        if conflict:
            if target_path.exists() and filecmp.cmp(file_path, target_path, shallow=False):
                duplicates.append((file_path, target_path))
            else:
                errors.append((file_path, conflict))
        else:
            moves.append((file_path, target_path))

    # Report what will happen
    print(f"\nPlanned operations:")
    print(f"  Moves: {len(moves)}")
    print(f"  Duplicates (can delete): {len(duplicates)}")
    print(f"  Errors: {len(errors)}")

    if dry_run:
        print("\nDry run mode - showing first 10 moves:")
        for source, target in moves[:10]:
            print(f"  {source} -> {target}")
        if len(moves) > 10:
            print(f"  ... and {len(moves) - 10} more")

        if duplicates:
            print(f"\nDuplicates (can delete source):")
            for source, target in duplicates[:5]:
                print(f"  {source} (identical to {target})")
            if len(duplicates) > 5:
                print(f"  ... and {len(duplicates) - 5} more")
    else:
        # Execute moves
        print("\nMoving files...")
        move_errors = 0

        for source, target in moves:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                print(f"  {source.name} -> {target}")
            except PermissionError as e:
                errors.append((source, f"Permission denied: {e}"))
                move_errors += 1
            except Exception as e:
                errors.append((source, f"Move failed: {e}"))
                move_errors += 1

        if move_errors == 0:
            print("All moves completed successfully!")

        if duplicates:
            print(f"\nFound {len(duplicates)} duplicate files (can be deleted):")
            for source, target in duplicates:
                print(f"  {source}")

    # Report errors
    if errors:
        print(f"\nEncountered {len(errors)} errors:", file=sys.stderr)
        for file_path, error in errors:
            print(f"  {file_path}: {error}", file=sys.stderr)
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="archivist",
        description="Organize media files by date into YYYY/YYYY-MM-DD directory structure"
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Source directory containing media files"
    )
    parser.add_argument(
        "target",
        type=Path,
        help="Target directory for organized files"
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be done without moving files"
    )
    parser.add_argument(
        "--ext",
        action="store_true",
        help="Group files by extension within date folders (default: don't group)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of photos to process per batch for progress updates (default: 50)"
    )
    parser.add_argument(
        "--skip-flag-check",
        action="store_true",
        help="Skip checking for immutable flags on source files"
    )

    args = parser.parse_args()

    exit_code = organize_media(
        source_dir=args.source,
        target_dir=args.target,
        group_by_extension=args.ext,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        skip_flag_check=args.skip_flag_check
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
