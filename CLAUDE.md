# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a media organization toolkit with four main tools:
1. **archivist.py** - Automatically sorts photos/videos by date into YYYY/YYYY-MM-DD structure
2. **lightbox.py** - Fast JPEG viewer with macOS color tagging support
3. **palette.py** - Batch processes images based on their color tags
4. **vault.py** - Copies `~/Pictures` to the SAN and reports what is already there

For user documentation, see README.md.

## Running the Scripts

The script uses uv's inline script feature for dependency management:

```bash
# Basic usage
./archivist.py SOURCE_DIR TARGET_DIR

# Dry run (see what would happen without moving files)
./archivist.py SOURCE_DIR TARGET_DIR --dry-run

# Group by file extension (optional)
./archivist.py SOURCE_DIR TARGET_DIR --ext

# Adjust batch size for progress updates (default: 50)
./archivist.py SOURCE_DIR TARGET_DIR --batch-size 40

# Skip immutable flag check (if you know files can be moved)
./archivist.py SOURCE_DIR TARGET_DIR --skip-flag-check

# Delete source files that are already in the archive (identical content)
./archivist.py SOURCE_DIR TARGET_DIR --delete-duplicates

# Treat metadata-only differences (e.g. Lightroom XMP) as duplicates too
./archivist.py SOURCE_DIR TARGET_DIR --delete-duplicates --compare image
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

5. **Conflict Detection**: Files whose target path is already occupied are collected and compared via `compare_pairs` to separate duplicates from real conflicts
   - `--check-duplicates` enables the (expensive) content comparison; without it every occupied target is an error
   - `--compare bytes` (default) uses `filecmp.cmp`; `--compare image` uses `extract_image_hashes` (ExifTool `ImageDataHash` with `-api RequestAll=3`) so files differing only in metadata still count as duplicates, falling back to `filecmp.cmp` for formats with no image hash
   - `--delete-duplicates` implies `--check-duplicates` and deletes source files judged duplicates; name collisions holding a different photo are still reported as errors, never deleted
   - `--overwrite` skips conflict checks entirely

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

## Image Viewer (lightbox.py)

A PyQt5-based JPEG viewer for reviewing and tagging photos.

**Key Components:**
- `ImageViewer`: Main window with image display and keyboard handling
- Uses `osxmetadata` library to read/write macOS Finder tags
- Only displays JPEG files (`.jpg`, `.jpeg`)
- Automatically applies EXIF orientation for correct portrait/landscape display

**Tag Shortcuts:**
- Numbers 1-7 apply color tags (Red, Orange, Yellow, Green, Blue, Purple, Gray)
- Number 0 clears all tags
- H key shows help dialog
- PgUp/PgDn to jump to first/last image

## Tag Processor (palette.py)

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

## SAN Archiver (vault.py)

Replicates `~/Pictures` to `/Volumes/data/Fotos` (SMB) and reports what is already
there. stdlib only — rsync does the copying.

**Subcommands:**
- `sync [-n]`: rsync `~/Pictures/{Albums,YYYY}` to the SAN, one invocation per directory
- `check PATH [--checksum] [--limit N] [--extra] [-q]`: compare a file or directory
  against the SAN; exit 0 only when everything matches

**Key invariants — do not break these:**
- **`sync` must never pass `--delete`.** The SAN holds far more than the local disk
  (12,528 files under `2025/` against 2,488 locally), so a single `--delete` would
  destroy ~10,000 archived files. The rsync argv is built from a fixed list with no
  passthrough, and `build_rsync` asserts no `--del*` flag is present.
- **`require_smb_target()` gates both subcommands.** An unmounted share leaves
  `/Volumes/data/Fotos` resolvable as an empty local directory, which would make
  `sync` fill the boot disk and `check` report everything missing. It asserts via
  `smbutil smbstat` (stdout must contain `Object Type:`) and `smbutil statshares -m`
  (`SERVER_NAME` must equal `SMB_SERVER`). **Both smbutil subcommands exit 0 even on
  failure**, writing errors to stderr or printing an empty table — parse stdout, never
  the return code. `statshares -m` accepts only a mount point, not a subdirectory.
- **macOS ships openrsync** (protocol 29, "2.6.9 compatible"), not GNU rsync 3.x.
  `--info=progress2`, `--no-perms` and `--mkpath` do not exist. `-rlt` is used rather
  than `-a` because SMB cannot preserve owner/group/perms; `--no-perms` is unnecessary
  since `-rlt` never requests them. `-t` is essential — `check` compares mtimes.

**Comparison basis:** size plus whole-second mtime. Measured on this share, local and
SAN mtimes agree exactly with sub-second precision always zero, so there is no SMB
rounding to absorb. `--checksum` is available but costs ~85 minutes per 63 GB.

Finder colour tags are not preserved; the SAN stores no extended attributes.

## recipes.txt

Contains film simulation recipes (Fujifilm camera presets) - not related to the media organization functionality.

## Workflow

The complete workflow is:
1. Import photos → `archivist.py` (organize by date)
2. Review photos → `lightbox.py` (apply color tags)
3. Process tags → `palette.py` (sort into output folders)
4. Archive → `vault.py sync`, then `vault.py check PATH` before deleting locally
