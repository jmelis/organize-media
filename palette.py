#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "osxmetadata>=1.3.0",
# ]
# ///
"""
Process tagged images based on macOS color tags.

Usage:
    ./palette.py SOURCE_DIR [TARGET_DIR] [--dry-run]

If TARGET_DIR is not provided, subdirectories will be created in SOURCE_DIR.

Tag processing:
    Red (1):    Copy JPG to {target}/selection
    Orange (2): Copy RAF to {target}/process-raw
    Yellow (3): Copy JPG to {target}/process-jpg
    Gray (7):   MOVE both JPG and RAF to {target}/delete
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Optional

from osxmetadata import (
    OSXMetaData,
    Tag,
    FINDER_COLOR_RED,
    FINDER_COLOR_ORANGE,
    FINDER_COLOR_YELLOW,
    FINDER_COLOR_GRAY,
)


# Create tag objects
TAG_RED = Tag("Red", FINDER_COLOR_RED)
TAG_ORANGE = Tag("Orange", FINDER_COLOR_ORANGE)
TAG_YELLOW = Tag("Yellow", FINDER_COLOR_YELLOW)
TAG_GRAY = Tag("Gray", FINDER_COLOR_GRAY)

# Tag to action mapping
TAG_ACTIONS = {
    TAG_RED: ("selection", "jpg", "copy"),       # Copy JPG to selection
    TAG_ORANGE: ("process-raw", "raf", "copy"),  # Copy RAF to process-raw
    TAG_YELLOW: ("process-jpg", "jpg", "copy"),  # Copy JPG to process-jpg
    TAG_GRAY: ("delete", "both", "move"),        # Move both to delete
}


def get_file_tags(path: Path) -> List[Tag]:
    """Get color tags for a file."""
    try:
        meta = OSXMetaData(str(path))
        return meta.tags
    except Exception as e:
        print(f"Warning: Could not read tags for {path}: {e}", file=sys.stderr)
        return []


def find_corresponding_raf(jpg_path: Path) -> Optional[Path]:
    """Find the corresponding RAF file for a JPG file."""
    raf_path = jpg_path.with_suffix('.RAF')
    if raf_path.exists():
        return raf_path

    # Try lowercase
    raf_path = jpg_path.with_suffix('.raf')
    if raf_path.exists():
        return raf_path

    return None


def discover_jpg_files(source_dir: Path) -> List[Path]:
    """Discover all JPG files in source directory (non-recursive)."""
    jpg_files = []
    for ext in ['.jpg', '.jpeg', '.JPG', '.JPEG']:
        jpg_files.extend(source_dir.glob(f'*{ext}'))
    return sorted(jpg_files)


def process_tagged_images(
    source_dir: Path,
    target_dir: Path,
    dry_run: bool = False
) -> int:
    """
    Process tagged images based on their color tags.

    Returns:
        Number of errors encountered
    """
    if not source_dir.is_dir():
        print(f"Error: Source '{source_dir}' is not a directory", file=sys.stderr)
        return 1

    if not target_dir.is_dir():
        print(f"Error: Target '{target_dir}' is not a directory", file=sys.stderr)
        return 1

    print(f"Scanning {source_dir} for tagged JPG files...")
    jpg_files = discover_jpg_files(source_dir)
    print(f"Found {len(jpg_files)} JPG files")

    # Collect actions to perform
    actions = []
    errors = []

    for jpg_path in jpg_files:
        tags = get_file_tags(jpg_path)

        # Check each tag and queue appropriate actions
        for tag in tags:
            if tag not in TAG_ACTIONS:
                continue

            subdir, file_type, operation = TAG_ACTIONS[tag]
            target_subdir = target_dir / subdir

            if file_type == "jpg":
                # Copy/move JPG
                actions.append((jpg_path, target_subdir / jpg_path.name, operation))

            elif file_type == "raf":
                # Copy/move RAF
                raf_path = find_corresponding_raf(jpg_path)
                if raf_path:
                    actions.append((raf_path, target_subdir / raf_path.name, operation))
                else:
                    errors.append((jpg_path, f"No corresponding RAF file found for orange tag"))

            elif file_type == "both":
                # Copy/move both JPG and RAF
                actions.append((jpg_path, target_subdir / jpg_path.name, operation))
                raf_path = find_corresponding_raf(jpg_path)
                if raf_path:
                    actions.append((raf_path, target_subdir / raf_path.name, operation))
                else:
                    # For gray tag, if no RAF exists, just move the JPG
                    pass

    # Remove duplicates while preserving order
    seen = set()
    unique_actions = []
    for action in actions:
        if action not in seen:
            seen.add(action)
            unique_actions.append(action)

    # Report what will happen
    copy_actions = [a for a in unique_actions if a[2] == "copy"]
    move_actions = [a for a in unique_actions if a[2] == "move"]

    print(f"\nPlanned operations:")
    print(f"  Copies: {len(copy_actions)}")
    print(f"  Moves: {len(move_actions)}")
    print(f"  Errors: {len(errors)}")

    if dry_run:
        print("\nDry run mode - showing actions:")

        # Group by operation and target directory
        by_dir = {}
        for source, target, operation in unique_actions:
            key = (target.parent, operation)
            if key not in by_dir:
                by_dir[key] = []
            by_dir[key].append((source, target))

        for (target_dir_path, operation), files in sorted(by_dir.items()):
            print(f"\n{operation.upper()} to {target_dir_path}:")
            for source, target in files[:10]:
                print(f"  {source.name}")
            if len(files) > 10:
                print(f"  ... and {len(files) - 10} more")

    else:
        # Execute actions
        print("\nProcessing files...")

        for source, target, operation in unique_actions:
            try:
                # Create target directory if needed
                target.parent.mkdir(parents=True, exist_ok=True)

                # Check if target already exists
                if target.exists():
                    print(f"  Skipping {source.name} - already exists at {target}")
                    continue

                # Perform operation
                if operation == "copy":
                    shutil.copy2(source, target)
                    print(f"  Copied {source.name} -> {target.parent.name}/")
                elif operation == "move":
                    shutil.move(str(source), str(target))
                    print(f"  Moved {source.name} -> {target.parent.name}/")

            except Exception as e:
                errors.append((source, f"{operation} failed: {e}"))

    # Report errors
    if errors:
        print(f"\nEncountered {len(errors)} errors:", file=sys.stderr)
        for file_path, error in errors:
            print(f"  {file_path.name}: {error}", file=sys.stderr)
        return 1

    print("\nProcessing complete!")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="palette",
        description="Process tagged images based on macOS color tags"
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Source directory containing tagged images"
    )
    parser.add_argument(
        "target",
        type=Path,
        nargs="?",
        help="Target directory for processed files (default: same as source)"
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be done without processing files"
    )

    args = parser.parse_args()

    # Use source as target if target not provided
    target_dir = args.target if args.target else args.source

    exit_code = process_tagged_images(
        source_dir=args.source,
        target_dir=target_dir,
        dry_run=args.dry_run
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
