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
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def check_immutable_flags(source_dir: Path) -> bool:
    """
    Check if any files have the immutable flag set (macOS 'uchg' flag).
    Uses native find command for reliable macOS flag detection.
    Returns True if immutable flags found.
    """
    try:
        result = subprocess.run(
            ["/usr/bin/find", str(source_dir), "-type", "f", "-flags", "+uchg"],
            capture_output=True,
            text=True,
            timeout=30
        )
        # If there's any output, immutable files were found
        return bool(result.stdout.strip())
    except Exception:
        # If find command fails, assume no immutable flags found
        # (user might not be on macOS or find command not available)
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


def perform_move(source: Path, target: Path) -> Tuple[Path, Path, Optional[str]]:
    """
    Perform a single file move operation.
    Returns (source, target, error_message) where error_message is None if successful.

    Args:
        source: Source file path
        target: Target file path
    """
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return (source, target, None)
    except PermissionError as e:
        return (source, target, f"Permission denied: {e}")
    except Exception as e:
        return (source, target, f"Move failed: {e}")


def extract_image_hashes(
    files: List[Path],
    et: exiftool.ExifToolHelper,
    batch_size: int = 50
) -> Dict[Path, str]:
    """
    Extract ImageDataHash (a hash of the image data only, ignoring metadata) for
    each file using batched ExifTool calls.
    Returns dict mapping file path to hash; files whose format doesn't support the
    hash are simply absent from the result.
    """
    if not files:
        return {}

    tag = "File:ImageDataHash"
    results: Dict[Path, str] = {}
    total = len(files)

    with tqdm(total=total, desc="Hashing image data", unit="file") as pbar:
        for i in range(0, total, batch_size):
            batch = files[i:i + batch_size]
            metadata_list = et.get_tags(
                batch, tags="ImageDataHash", params=["-api", "RequestAll=3"]
            )

            for file_path, metadata in zip(batch, metadata_list):
                image_hash = metadata.get(tag)
                if image_hash:
                    results[file_path] = image_hash

            pbar.update(len(batch))

    return results


def compare_pairs(
    pairs: List[Tuple[Path, Path]],
    compare_mode: str,
    batch_size: int = 50
) -> Dict[Tuple[Path, Path], bool]:
    """
    Compare (source, target) pairs and report which ones hold the same photo.

    compare_mode:
        "bytes" - files must be byte-for-byte identical
        "image" - only the image data must match; metadata (XMP, EXIF edits
                  written by Lightroom and friends) may differ. Falls back to a
                  byte comparison for formats with no image data hash.
    """
    if compare_mode == "bytes":
        return {
            (source, target): filecmp.cmp(source, target, shallow=False)
            for source, target in pairs
        }

    # Hash every file involved once, even if it appears in several pairs
    unique_files = sorted({f for pair in pairs for f in pair})
    with exiftool.ExifToolHelper() as et:
        hashes = extract_image_hashes(unique_files, et, batch_size)

    results = {}
    for source, target in pairs:
        source_hash = hashes.get(source)
        target_hash = hashes.get(target)
        if source_hash and target_hash:
            results[(source, target)] = source_hash == target_hash
        else:
            # No image hash available (unsupported format) - fall back to bytes
            results[(source, target)] = filecmp.cmp(source, target, shallow=False)

    return results


def organize_media(
    source_dir: Path,
    target_dir: Path,
    group_by_extension: bool = False,
    dry_run: bool = False,
    batch_size: int = 50,
    skip_flag_check: bool = False,
    check_duplicates: bool = False,
    overwrite: bool = False,
    delete_duplicates: bool = False,
    compare_mode: str = "bytes"
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
        check_duplicates: Use expensive file comparison to detect duplicates (default: False)
        overwrite: Skip conflict checks and overwrite existing files (default: False)
        delete_duplicates: Delete source files already present at the target
            (implies check_duplicates, default: False)
        compare_mode: How to decide two files are the same, "bytes" or "image"
    """
    # Deleting is destructive, so never do it without verifying file contents
    if delete_duplicates:
        check_duplicates = True

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
        if check_immutable_flags(source_dir):
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
    occupied: List[Tuple[Path, Path]] = []  # target already exists, needs comparison

    for file_path, date in file_dates.items():
        target_path = calculate_target_path(file_path, date, target_dir, group_by_extension)

        # An in-place import must never delete its own archived file.
        if target_path.exists() and file_path.samefile(target_path):
            continue

        if overwrite:
            # Skip conflict checks, just move/overwrite
            moves.append((file_path, target_path))
        elif target_path.parent.is_file():
            errors.append((file_path, f"Target directory {target_path.parent} is a file"))
        elif target_path.exists():
            occupied.append((file_path, target_path))
        else:
            moves.append((file_path, target_path))

    # Decide which occupied targets are duplicates of their source
    if occupied:
        if check_duplicates:
            identical = compare_pairs(occupied, compare_mode, batch_size)
            for source, target in occupied:
                if identical[(source, target)]:
                    duplicates.append((source, target))
                else:
                    errors.append((source, f"Target {target} already exists with different content"))
        else:
            for source, target in occupied:
                errors.append((source, f"Target {target} already exists"))

    # Report what will happen
    print(f"\nPlanned operations:")
    print(f"  Moves: {len(moves)}")
    dup_label = "will delete" if delete_duplicates else "can delete"
    print(f"  Duplicates ({dup_label}): {len(duplicates)}")
    print(f"  Errors: {len(errors)}")

    if dry_run:
        print("\nDry run mode - showing first 10 moves:")
        for source, target in moves[:10]:
            print(f"  {source} -> {target}")
        if len(moves) > 10:
            print(f"  ... and {len(moves) - 10} more")

        if duplicates:
            action = "would delete source" if delete_duplicates else "can delete source"
            print(f"\nDuplicates ({action}):")
            for source, target in duplicates[:5]:
                print(f"  {source} (identical to {target})")
            if len(duplicates) > 5:
                print(f"  ... and {len(duplicates) - 5} more")
    else:
        # Execute moves with thread pool for parallel I/O
        print("\nMoving files...")
        move_errors = 0

        # Use ThreadPoolExecutor for parallel moves (8 threads for balanced I/O on separate volumes)
        with ThreadPoolExecutor(max_workers=8) as executor:
            # Submit all move tasks
            futures = {
                executor.submit(perform_move, source, target): (source, target)
                for source, target in moves
            }

            # Process completed moves with progress bar
            with tqdm(total=len(moves), desc="Progress", unit="file") as pbar:
                for future in as_completed(futures):
                    source, target, error = future.result()
                    if error:
                        errors.append((source, error))
                        move_errors += 1
                    pbar.update(1)

        if move_errors == 0:
            print("All moves completed successfully!")

        if duplicates:
            if delete_duplicates:
                print(f"\nDeleting {len(duplicates)} duplicate source files...")
                deleted = 0
                with tqdm(total=len(duplicates), desc="Deleting", unit="file") as pbar:
                    for source, target in duplicates:
                        try:
                            source.unlink()
                            deleted += 1
                        except Exception as e:
                            errors.append((source, f"Delete failed: {e}"))
                        pbar.update(1)
                print(f"Deleted {deleted} duplicate files.")
            else:
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
    parser.add_argument(
        "--check-duplicates",
        action="store_true",
        help="Use file comparison to detect duplicates (expensive, default: disabled)"
    )
    parser.add_argument(
        "--delete-duplicates",
        action="store_true",
        help="Delete source files already present at the target "
             "(implies --check-duplicates)"
    )
    parser.add_argument(
        "--compare",
        choices=["bytes", "image"],
        default="bytes",
        help="How to decide two files are the same: 'bytes' requires a byte-for-byte "
             "match, 'image' compares only the image data so files that differ just "
             "in metadata (e.g. XMP written by Lightroom) still count as duplicates "
             "(default: bytes)"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files without checking (fastest, default: disabled)"
    )

    args = parser.parse_args()

    exit_code = organize_media(
        source_dir=args.source,
        target_dir=args.target,
        group_by_extension=args.ext,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        skip_flag_check=args.skip_flag_check,
        check_duplicates=args.check_duplicates,
        overwrite=args.overwrite,
        delete_duplicates=args.delete_duplicates,
        compare_mode=args.compare
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
