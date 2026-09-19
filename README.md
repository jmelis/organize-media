# Media Organization Tools

A collection of Python scripts for organizing, viewing, and processing photos using macOS color tags.

## Tools

### 1. archivist.py - Date-based Media Organization

Automatically organizes photos and videos into a date-based directory structure by extracting metadata.

**Usage:**
```bash
./archivist.py SOURCE_DIR TARGET_DIR [--dry-run] [--ext] [--delete-duplicates] [--compare bytes|image]
```

**Features:**
- Extracts dates from EXIF metadata (photos) or creation timestamps (videos)
- Organizes into `YYYY/YYYY-MM-DD/` structure
- Optional extension grouping with `--ext` flag
- Batch processing with progress bars
- Detects and reports duplicates
- Deletes already-archived source files with `--delete-duplicates`
- Dry-run mode to preview changes

**Example:**
```bash
# Preview what would happen
./archivist.py ~/Downloads/photos ~/Pictures/organized --dry-run

# Actually organize the files
./archivist.py ~/Downloads/photos ~/Pictures/organized

# Re-running an import: delete sources already present in the archive
./archivist.py ~/Downloads/photos ~/Pictures/organized --delete-duplicates

# Same, but ignore metadata-only differences (e.g. XMP added by Lightroom)
./archivist.py ~/Downloads/photos ~/Pictures/organized --delete-duplicates --compare image
```

`--delete-duplicates` removes a source file only when the file already sitting at
its target path is the same photo (it implies `--check-duplicates`). Files that
share a name but hold a different photo are never deleted — they are reported as
errors so you can resolve them yourself.

`--compare` chooses what "the same photo" means:

| Mode | Meaning |
|---|---|
| `bytes` (default) | Byte-for-byte identical files. Fast, strictest. |
| `image` | Only the image data must match. Files that differ purely in metadata — an XMP block written by Lightroom, an edited EXIF tag, a Finder comment — still count as duplicates. |

Use `--compare image` when your source files have been opened by Lightroom or a
similar tool since they were archived: those write metadata back into the file,
so the bytes no longer match even though the photo is unchanged. Note that
deleting such a source discards the metadata it had gained.

### archivist-wd.py - Archive to WD Elements with PhotoPrism deduplication

An opinionated variant of `archivist.py`, reusing its EXIF/video date extraction
and `YYYY/YYYY-MM-DD/` paths. Each source directory is classified independently:
if its immediate files include a RAW, its supported media goes to
`/Volumes/WD Elements AE/Raws`; otherwise it goes to `Export`. A JPEG-only child
directory therefore goes to `Export` even when its parent has RAWs. Files without
a usable metadata date are reported and retained. Symlinks, sidecars, and
unsupported files are left alone.

```bash
# Preview every operation (default is copy, with one hashing thread)
./archivist-wd.py ~/Desktop/"2025-10 London" --dry-run

# Copy new files; parallel source hashing is optional (use 1 for a spinning HDD)
./archivist-wd.py SOURCE --threads 4

# Move new files after verifying their copied contents; indexed files stay skipped
./archivist-wd.py SOURCE --move --dry-run

# Only delete already-indexed duplicates; leave unindexed files untouched
./archivist-wd.py SOURCE --delete-source --dry-run
```

`--copy` (default), `--move`, and `--delete-source` are mutually exclusive.
Remove `--dry-run` to execute. Only hashing is parallelized; archive writes are
sequential. Different files with colliding names receive `_2`, `_3`, etc. before
the extension. Existing files are never overwritten, including collisions
between files in the same import or a concurrently created destination.

The script hashes source files with whole-file SHA-1 and queries PhotoPrism's
stored hashes directly over `127.0.0.1:3306`, using a read-only transaction.
Credentials and optional `MARIADB_PORT` come from
`~/personal/git/photoprism/.env` (override with `--db-env PATH`). It does not use
`podman exec` or change database entries. Matches anywhere in the indexed
`Raws`, `Export`, or `Other` trees are considered, regardless of filename.
An indexed copy must still exist with the expected size to count as a match.

Copy/skip decisions trust the stored hash. Before `--delete-source` actually
removes anything, it reads and hashes the archived copy too; a stale index
cannot authorize deletion. Dry-run lists candidate deletions without doing this
extra archive-content verification. New copies are staged and verified before
publication; move removes the source only after successful copying. The script
first checks that `/Volumes/WD Elements AE/Raws` exists and exits with "not
mounted" if absent, then checks the WD volume UUID/mount and rejects overlapping
source/archive trees.

After importing, run PhotoPrism indexing through its usual workflow before
importing the same sources again. Until indexed, new copies are not database
matches and a repeated import will create numbered copies.

Run the isolated filesystem tests with `uv run test_archivist_wd.py`.

### 2. lightbox.py - Tagged Image Viewer

A fast image viewer for JPEGs with built-in macOS color tagging support.

**Usage:**
```bash
./lightbox.py <file_or_directory>
```

**Keyboard Shortcuts:**
- **Navigation:**
  - `←` / `→` - Previous / Next image
  - `PgUp` / `PgDn` - Jump to first / last image
  - `F` - Toggle fullscreen
  - `Q` / `Esc` - Quit (or exit fullscreen)
  - `H` - Show help

- **Color Tagging:**
  - `1` - Red tag (for final selection)
  - `2` - Orange tag (for RAW processing)
  - `3` - Yellow tag (for JPG processing)
  - `4-6` - Green, Blue, Purple tags
  - `7` - Gray tag (for deletion)
  - `0` - Clear all tags

**Features:**
- Native macOS look and feel with PyQt5
- High-quality image rendering with automatic EXIF rotation
- Color tag indicators displayed as colored dots in the status bar
- Tags are saved to macOS Finder metadata
- JPEG-only display (filters out RAW files)

### 3. palette.py - Batch Process Tagged Images

Processes images based on their color tags, copying or moving them to appropriate directories.

**Usage:**
```bash
./palette.py SOURCE_DIR [TARGET_DIR] [--dry-run]
```

If `TARGET_DIR` is not provided, subdirectories will be created in `SOURCE_DIR`.

**Tag Processing:**
- **Red (1)**: Copy JPG → `{target}/selection`
- **Orange (2)**: Copy RAF → `{target}/process-raw`
- **Yellow (3)**: Copy JPG → `{target}/process-jpg`
- **Gray (7)**: **MOVE** both JPG and RAF → `{target}/delete`

**Features:**
- Automatically creates target subdirectories
- Finds corresponding RAF files for JPEGs
- Skips files that already exist
- Dry-run mode to preview operations
- Detailed error reporting

### 4. vault.py - Copy to the SAN and Check What's There

Replicates `~/Pictures` to the SAN at `/Volumes/data/Fotos`, and answers whether a
given path is already safely there so you can decide what to delete locally.

**Usage:**
```bash
./vault.py sync [-n]
./vault.py check PATH [--checksum] [--limit N] [--extra] [-q]
```

**`sync`** copies `~/Pictures/Albums` and every `~/Pictures/YYYY` directory to the
SAN. It is additive: it never passes `--delete` to rsync, so files that exist only
on the SAN are left alone. Files that exist on both sides are updated from the local
copy. Anything not matching `Albums` or a four-digit year — `borked/`, the Photos and
Lightroom library bundles — is never touched.

**`check`** compares a file or directory against its SAN counterpart on size and
whole-second mtime, and exits 0 only when everything matches, so it composes:

```bash
./vault.py check ~/Pictures/2025/2025-10-05 && rm -rf ~/Pictures/2025/2025-10-05
```

```
✓ 2025/2025-10-05 — all 72 files present on the SAN, sizes and mtimes match

✗ 2026/2026-09-06 — 64 files checked, 64 missing
  MISSING (64):
    DSCF2587.RAF
    ... and 59 more (--limit 0 to list all)
```

| Option | Effect |
|---|---|
| `--checksum` | Also compare file contents. Slow — roughly 85 minutes per 63 GB over SMB. |
| `--limit N` | Cap entries listed per section (default 50; `0` lists all). |
| `--extra` | Also list files present on the SAN but not locally. Normal here, so off by default. |
| `-q`, `--quiet` | Print nothing; report the verdict through the exit code only. |

**Safety:** both subcommands first assert that `/Volumes/data/Fotos` really is the
expected SMB share, by name and by server address. If the share is unmounted, that
path can resolve to an empty local directory — which would make `sync` fill the boot
disk and `check` declare everything missing. Both refuse instead.

Note that macOS ships openrsync rather than GNU rsync, so `sync` sticks to flags
openrsync supports. Finder colour tags are not preserved: the SAN stores no extended
attributes.

## Workflow

### Complete Photo Organization Workflow

1. **Import and Organize by Date**
   ```bash
   # Import photos from camera/SD card and organize by date
   ./archivist.py ~/Downloads/camera ~/Pictures/2025 --dry-run
   ./archivist.py ~/Downloads/camera ~/Pictures/2025
   ```

2. **Review and Tag Images**
   ```bash
   # Open the organized folder in the image viewer
   ./lightbox.py ~/Pictures/2025/2025-10-28/

   # Use keyboard shortcuts to tag images:
   # - Press 1 for keepers (red tag)
   # - Press 2 for RAWs to process (orange tag)
   # - Press 3 for JPEGs to edit (yellow tag)
   # - Press 7 for images to delete (gray tag)
   # - Press H for help
   ```

3. **Process Tagged Images**
   ```bash
   # Preview what will happen (creates subdirectories in source folder)
   ./palette.py ~/Pictures/2025/2025-10-28 --dry-run

   # Process the tagged images (in-place)
   ./palette.py ~/Pictures/2025/2025-10-28

   # Or specify a different output directory
   ./palette.py ~/Pictures/2025/2025-10-28 ~/output
   ```

4. **Results**
   After processing, you'll have subdirectories with:
   - `selection/` - Your final selected JPEGs
   - `process-raw/` - RAF files ready for editing in Lightroom/etc
   - `process-jpg/` - JPEGs ready for quick edits
   - `delete/` - Files to review and delete

5. **Archive to the SAN and reclaim disk space**
   ```bash
   # See how much is not yet on the SAN
   ./vault.py sync --dry-run

   # Copy it across (use caffeinate so the Mac doesn't sleep mid-transfer)
   caffeinate -i ./vault.py sync

   # Confirm a folder is safely there before deleting the local copy
   ./vault.py check ~/Pictures/2025/2025-10-05 && rm -rf ~/Pictures/2025/2025-10-05
   ```

   `vault.py` never deletes anything itself — `check` gives you a verdict and an exit
   code, and the deletion stays your call.

## Requirements

All scripts use `uv` for dependency management with inline script metadata. Dependencies are automatically installed when you run the scripts.

**External dependencies:**
- `exiftool` - For EXIF metadata extraction (install via Homebrew: `brew install exiftool`)
- `ffmpeg` - For video metadata extraction (install via Homebrew: `brew install ffmpeg`)

**Python dependencies** (auto-installed by uv):
- `pyexiftool` - Python wrapper for exiftool
- `tqdm` - Progress bars
- `PyQt5` - GUI framework for image viewer
- `Pillow` - Image processing
- `osxmetadata` - macOS metadata/tags manipulation

## Installation

1. Install uv:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Install external dependencies:
   ```bash
   brew install exiftool ffmpeg
   ```

3. Make scripts executable:
   ```bash
   chmod +x archivist.py lightbox.py palette.py
   ```

4. Run any script - dependencies will be installed automatically on first run.

## Tips

- **Use dry-run first**: Always use `--dry-run` to preview operations before executing
- **Backup your files**: Keep backups of important photos before organizing
- **Tag incrementally**: You can tag images over multiple sessions - tags persist in macOS Finder
- **Filter by tag in Finder**: Use Finder's tag filter to see all tagged images across folders
- **Multiple tags**: Images can have multiple tags - the processor handles each tag's action

## License

See LICENSE file for details.
