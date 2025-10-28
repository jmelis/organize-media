# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a media organization toolkit with three main tools:
1. **organize_media.py** - Automatically sorts photos/videos by date into YYYY/YYYY-MM-DD structure
2. **image-viewer.py** - Fast JPEG viewer with macOS color tagging support
3. **process-tagged-images.py** - Batch processes images based on their color tags

For user documentation, see README.md.

## Running the Script

The script uses uv's inline script feature for dependency management:

```bash
# Basic usage
./organize_media.py SOURCE_DIR TARGET_DIR

# Dry run (see what would happen without moving files)
./organize_media.py SOURCE_DIR TARGET_DIR --dry-run

# Group by file extension (optional)
./organize_media.py SOURCE_DIR TARGET_DIR --ext

# Adjust batch size for progress updates (default: 50)
./organize_media.py SOURCE_DIR TARGET_DIR --batch-size 40

# Skip immutable flag check (if you know files can be moved)
./organize_media.py SOURCE_DIR TARGET_DIR --skip-flag-check
```

By default, files are placed directly in date folders: `YYYY/YYYY-MM-DD/filename`. Use `--ext` to group by extension within date folders.

The `--batch-size` option controls how many photos are processed in each batch before updating the progress bar. Smaller batches give more frequent updates but may be slightly slower. Default is 50, which provides a good balance.

### Immutable Flag Check

On macOS, files can have an immutable flag (`uchg`) that prevents them from being moved or deleted. The script automatically checks for this flag before processing and prompts you to remove it if found:

```bash
sudo chflags -R nouchg SOURCE_DIR
```

Use `--skip-flag-check` to bypass this check if you know your files don't have immutable flags set.

## Architecture

### Single-File Design
The entire application is in `organize_media.py` - a self-contained uv script with inline dependency declarations (pyexiftool).

### Core Processing Pipeline

1. **Discovery** (`discover_files`): Recursively finds media files by extension
   - Photos: .jpg, .jpeg, .arw, .sr2, .raf
   - Videos: .mp4, .mov

2. **Immutable Flag Check** (`check_immutable_flags`): Samples files to detect macOS immutable flags
   - Checks up to 100 files (or all if <1000 total)
   - Prompts user to remove flags with `sudo chflags -R nouchg` if found
   - Can be skipped with `--skip-flag-check`

3. **Date Extraction**:
   - Photos: Batch-processed via ExifToolHelper to extract `EXIF:DateTimeOriginal`
   - Videos: Individual ffmpeg calls to extract `creation_time` from metadata

4. **Path Calculation** (`calculate_target_path`): Constructs target paths as `TARGET/YYYY/YYYY-MM-DD/[ext/]filename`

5. **Conflict Detection** (`check_file_conflict`): Uses `filecmp.cmp` to identify identical files (duplicates) vs. conflicting files

6. **Execution**: Moves files using `shutil.move`, reports duplicates that can be safely deleted

### Error Handling Strategy

The script accumulates errors during processing rather than failing fast:
- Files without metadata are tracked but don't stop processing
- Move failures are caught and reported
- Returns exit code 1 if any errors occurred

### Batch Processing Optimization

Photos are processed in configurable batches via ExifToolHelper (`extract_photo_dates`) for performance. Progress is displayed using tqdm with a real-time progress bar showing percentage, ETA, and processing speed. The batch size (default: 50) determines how often the progress bar updates. Videos require individual ffmpeg calls since ffmpeg doesn't batch metadata extraction effectively, but each video shows incremental progress in the tqdm bar.

## Dependencies

- `pyexiftool`: EXIF metadata extraction (installed via uv)
- `tqdm`: Progress bar for batch processing (installed via uv)
- `exiftool`: External binary (must be installed separately)
- `ffmpeg`: External binary for video metadata (must be installed separately)

## Image Viewer (image-viewer.py)

A PyQt5-based JPEG viewer for reviewing and tagging photos.

**Key Components:**
- `ColorTagIndicator`: Widget that displays colored dots for active tags
- `ImageViewer`: Main window with image display and keyboard handling
- Uses `osxmetadata` library to read/write macOS Finder tags
- Only displays JPEG files (`.jpg`, `.jpeg`)
- Automatically applies EXIF orientation for correct portrait/landscape display

**Tag Shortcuts:**
- Numbers 1-7 apply color tags (Red, Orange, Yellow, Green, Blue, Purple, Gray)
- Number 0 clears all tags
- H key shows help dialog

## Tag Processor (process-tagged-images.py)

Batch processes images based on macOS color tags.

**Processing Rules:**
- Red (1): Copy JPG → `{target}/selection`
- Orange (2): Copy RAF → `{target}/process-raw`
- Yellow (3): Copy JPG → `{target}/process-jpg`
- Gray (7): Move both JPG and RAF → `{target}/delete`

**Key Functions:**
- `discover_jpg_files()`: Recursively finds all JPEGs
- `get_file_tags()`: Reads macOS color tags via osxmetadata
- `find_corresponding_raf()`: Locates matching RAW file for a JPEG
- `process_tagged_images()`: Main processing loop

## recipes.txt

Contains film simulation recipes (Fujifilm camera presets) - not related to the media organization functionality.

## Workflow

The complete workflow is:
1. Import photos → `organize_media.py` (organize by date)
2. Review photos → `image-viewer.py` (apply color tags)
3. Process tags → `process-tagged-images.py` (sort into output folders)
