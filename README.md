# Media Organization Tools

A collection of Python scripts for organizing, viewing, and processing photos using macOS color tags.

## Tools

### 1. organize_media.py - Date-based Media Organization

Automatically organizes photos and videos into a date-based directory structure by extracting metadata.

**Usage:**
```bash
./organize_media.py SOURCE_DIR TARGET_DIR [--dry-run] [--ext]
```

**Features:**
- Extracts dates from EXIF metadata (photos) or creation timestamps (videos)
- Organizes into `YYYY/YYYY-MM-DD/` structure
- Optional extension grouping with `--ext` flag
- Batch processing with progress bars
- Detects and reports duplicates
- Dry-run mode to preview changes

**Example:**
```bash
# Preview what would happen
./organize_media.py ~/Downloads/photos ~/Pictures/organized --dry-run

# Actually organize the files
./organize_media.py ~/Downloads/photos ~/Pictures/organized
```

### 2. image-viewer.py - Tagged Image Viewer

A fast image viewer for JPEGs with built-in macOS color tagging support.

**Usage:**
```bash
./image-viewer.py <file_or_directory>
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

### 3. process-tagged-images.py - Batch Process Tagged Images

Processes images based on their color tags, copying or moving them to appropriate directories.

**Usage:**
```bash
./process-tagged-images.py SOURCE_DIR [TARGET_DIR] [--dry-run]
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

## Workflow

### Complete Photo Organization Workflow

1. **Import and Organize by Date**
   ```bash
   # Import photos from camera/SD card and organize by date
   ./organize_media.py ~/Downloads/camera ~/Pictures/2025 --dry-run
   ./organize_media.py ~/Downloads/camera ~/Pictures/2025
   ```

2. **Review and Tag Images**
   ```bash
   # Open the organized folder in the image viewer
   ./image-viewer.py ~/Pictures/2025/2025-10-28/

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
   ./process-tagged-images.py ~/Pictures/2025/2025-10-28 --dry-run

   # Process the tagged images (in-place)
   ./process-tagged-images.py ~/Pictures/2025/2025-10-28

   # Or specify a different output directory
   ./process-tagged-images.py ~/Pictures/2025/2025-10-28 ~/output
   ```

4. **Results**
   After processing, you'll have subdirectories with:
   - `selection/` - Your final selected JPEGs
   - `process-raw/` - RAF files ready for editing in Lightroom/etc
   - `process-jpg/` - JPEGs ready for quick edits
   - `delete/` - Files to review and delete

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
   chmod +x organize_media.py image-viewer.py process-tagged-images.py
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
