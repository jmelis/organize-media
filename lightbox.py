#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pillow>=10.0.0",
#     "pyexiftool>=0.5.0",
#     "PyQt5>=5.15.0",
#     "osxmetadata>=1.3.0",
# ]
# ///
"""
Simple image viewer with arrow key navigation and fullscreen toggle.

Usage:
    ./lightbox.py <file_or_directory>

Keys:
    Left/Right Arrow: Navigate between images
    PgUp/PgDn: Jump to first/last image
    F: Toggle fullscreen
    H: Show help
    Escape: Exit fullscreen or quit
    Q: Quit
    1-7: Apply color tags (Red, Orange, Yellow, Green, Blue, Purple, Gray)
    0: Clear all tags
"""

import sys
from pathlib import Path
from PIL import Image, ImageOps
import io
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QStatusBar, QWidget, QHBoxLayout, QMessageBox
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QPalette
from PyQt5.QtCore import Qt, QTimer
from osxmetadata import (
    OSXMetaData,
    Tag,
    FINDER_COLOR_RED,
    FINDER_COLOR_ORANGE,
    FINDER_COLOR_YELLOW,
    FINDER_COLOR_GREEN,
    FINDER_COLOR_BLUE,
    FINDER_COLOR_PURPLE,
    FINDER_COLOR_GRAY,
)

# Supported image extensions (JPEG only)
IMAGE_EXTENSIONS = {'.jpg', '.jpeg'}

# macOS color tags mapping
COLOR_TAGS = {
    1: (Tag("Red", FINDER_COLOR_RED), QColor(255, 59, 48)),       # macOS Red
    2: (Tag("Orange", FINDER_COLOR_ORANGE), QColor(255, 149, 0)),    # macOS Orange
    3: (Tag("Yellow", FINDER_COLOR_YELLOW), QColor(255, 204, 0)),    # macOS Yellow
    4: (Tag("Green", FINDER_COLOR_GREEN), QColor(40, 205, 65)),     # macOS Green
    5: (Tag("Blue", FINDER_COLOR_BLUE), QColor(0, 122, 255)),      # macOS Blue
    6: (Tag("Purple", FINDER_COLOR_PURPLE), QColor(175, 82, 222)),   # macOS Purple
    7: (Tag("Gray", FINDER_COLOR_GRAY), QColor(142, 142, 147)),    # macOS Gray
}


class ImageViewer(QMainWindow):
    def __init__(self, image_files, start_index=0):
        super().__init__()

        self.image_files = sorted(image_files)
        self.current_index = start_index
        self.current_pil_image = None

        # Setup main window
        self.setWindowTitle("Image Viewer")
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet("background-color: black;")

        # Create image label
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)
        self.setCentralWidget(self.image_label)

        # Create status bar with custom label for rich text support
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("background-color: black; color: white;")

        # Add a permanent label to the status bar that supports HTML
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.RichText)
        self.status_bar.addPermanentWidget(self.status_label, 1)

        if not self.image_files:
            print("Error: No images found", file=sys.stderr)
            sys.exit(1)

        # Load first image
        self.load_and_display()

    def load_image(self, path):
        """Load an image file, handling RAW formats via exiftool and EXIF orientation."""
        try:
            # Try loading directly with PIL first
            try:
                img = Image.open(path)
                img.load()  # Force load to catch any issues
                # Apply EXIF orientation (handles portrait/rotated images)
                img = ImageOps.exif_transpose(img)
                return img
            except Exception:
                # If PIL fails, try extracting preview from RAW using exiftool
                if path.suffix.lower() in {'.arw', '.sr2', '.raf', '.cr2', '.nef'}:
                    import exiftool
                    with exiftool.ExifToolHelper() as et:
                        # Get preview image from RAW file
                        result = et.execute(b"-PreviewImage", b"-b", str(path).encode())
                        if result:
                            img = Image.open(io.BytesIO(result))
                            # Apply EXIF orientation for RAW preview
                            img = ImageOps.exif_transpose(img)
                            return img
                raise
        except Exception as e:
            print(f"Error loading {path.name}: {e}", file=sys.stderr)
            return None

    def pil_to_qpixmap(self, pil_image):
        """Convert PIL image to QPixmap."""
        # Convert to RGB if needed
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        # Convert to bytes
        data = pil_image.tobytes("raw", "RGB")
        qimage = QImage(data, pil_image.width, pil_image.height, pil_image.width * 3, QImage.Format_RGB888)
        return QPixmap.fromImage(qimage)

    def get_file_tags(self, path):
        """Get color tags for a file."""
        try:
            meta = OSXMetaData(str(path))
            tags = meta.tags

            # Match tags to our color mapping
            result = []
            for num, (tag_obj, color) in COLOR_TAGS.items():
                if tag_obj in tags:
                    result.append((tag_obj.name, color))
            return result
        except Exception as e:
            print(f"Error reading tags: {e}", file=sys.stderr)
            return []

    def set_file_tag(self, path, tag_number):
        """Set a color tag on a file (toggles if already set)."""
        try:
            if tag_number not in COLOR_TAGS:
                return

            meta = OSXMetaData(str(path))
            tag_obj, color = COLOR_TAGS[tag_number]

            # Toggle: if tag exists, remove it; otherwise add it
            current_tags = meta.tags
            if tag_obj in current_tags:
                meta.tags = [t for t in current_tags if t != tag_obj]
            else:
                meta.tags = list(current_tags) + [tag_obj]

            # Refresh the status bar to show updated tags
            tags = self.get_file_tags(path)
            tag_html = self.get_tag_html(tags)
            status_text = f"{self.current_index + 1}/{len(self.image_files)} - {path.name}{tag_html}"
            self.status_label.setText(status_text)

        except Exception as e:
            print(f"Error setting tag: {e}", file=sys.stderr)

    def clear_file_tags(self, path):
        """Clear all color tags from a file."""
        try:
            meta = OSXMetaData(str(path))
            # Remove all color tags
            current_tags = meta.tags
            color_tag_objs = [tag_obj for tag_obj, _ in COLOR_TAGS.values()]
            meta.tags = [t for t in current_tags if t not in color_tag_objs]

            # Refresh the status bar
            status_text = f"{self.current_index + 1}/{len(self.image_files)} - {path.name}"
            self.status_label.setText(status_text)

        except Exception as e:
            print(f"Error clearing tags: {e}", file=sys.stderr)

    def get_tag_html(self, tags):
        """Generate HTML for colored tag dots."""
        if not tags:
            return ""

        html_parts = []
        for tag_name, color in tags:
            # Create a colored circle using HTML/CSS with larger font
            html_parts.append(
                f'<span style="color: rgb({color.red()}, {color.green()}, {color.blue()}); font-size: 16pt;">●</span>'
            )
        return "  " + "".join(html_parts)

    def load_and_display(self):
        """Load and display the current image."""
        if not self.image_files or self.current_index >= len(self.image_files):
            return

        path = self.image_files[self.current_index]

        # Get tags for this image
        tags = self.get_file_tags(path)
        tag_html = self.get_tag_html(tags)

        # Update status and title
        status_text = f"{self.current_index + 1}/{len(self.image_files)} - {path.name}{tag_html}"
        self.status_label.setText(status_text)
        self.setWindowTitle(f"Image Viewer - {path.name}")

        # Load image
        self.current_pil_image = self.load_image(path)
        if self.current_pil_image is None:
            return

        self.update_display()

    def update_display(self):
        """Update the display with the current image scaled to fit window."""
        if self.current_pil_image is None:
            return

        # Get available space (window size minus status bar)
        available_width = self.width()
        available_height = self.height() - self.status_bar.height()

        # Calculate scaling to fit while maintaining aspect ratio
        img_width, img_height = self.current_pil_image.size
        scale = min(available_width / img_width, available_height / img_height)
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)

        # Resize with high quality
        resized_image = self.current_pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Convert to QPixmap and display
        pixmap = self.pil_to_qpixmap(resized_image)
        self.image_label.setPixmap(pixmap)

    def next_image(self):
        """Show next image."""
        if self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self.load_and_display()

    def prev_image(self):
        """Show previous image."""
        if self.current_index > 0:
            self.current_index -= 1
            self.load_and_display()

    def first_image(self):
        """Show first image."""
        if self.current_index != 0:
            self.current_index = 0
            self.load_and_display()

    def last_image(self):
        """Show last image."""
        last_index = len(self.image_files) - 1
        if self.current_index != last_index:
            self.current_index = last_index
            self.load_and_display()

    def show_help(self):
        """Display help dialog."""
        help_text = """Image Viewer - Keyboard Shortcuts

Navigation:
  ← / →       Previous / Next image
  PgUp/PgDn   First / Last image
  F           Toggle fullscreen
  Q / Esc     Quit (or exit fullscreen)

Color Tagging:
  1        Red tag (for selection)
  2        Orange tag (for RAW processing)
  3        Yellow tag (for JPG processing)
  4        Green tag
  5        Blue tag
  6        Purple tag
  7        Gray tag (for deletion)
  0        Clear all tags

Other:
  H        Show this help

Tags are saved to macOS Finder metadata."""

        msg = QMessageBox(self)
        msg.setWindowTitle("Image Viewer Help")
        msg.setText(help_text)
        msg.setIcon(QMessageBox.NoIcon)

        # Use a monospace font for better alignment
        font = msg.font()
        font.setFamily("Monaco")
        msg.setFont(font)

        # Enable auto fill background
        msg.setAutoFillBackground(True)

        # Set color palette for black background and white text
        palette = msg.palette()
        palette.setColor(QPalette.Window, QColor(0, 0, 0))  # Black background
        palette.setColor(QPalette.WindowText, QColor(255, 255, 255))  # White text
        palette.setColor(QPalette.Base, QColor(0, 0, 0))  # Black base
        palette.setColor(QPalette.Text, QColor(255, 255, 255))  # White text
        palette.setColor(QPalette.Button, QColor(51, 51, 51))  # Dark gray button
        palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))  # White button text
        msg.setPalette(palette)

        # Also style all child widgets (labels, buttons, etc.)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: black;
            }
            QLabel {
                color: white;
                background-color: black;
            }
            QPushButton {
                background-color: #333;
                color: white;
                padding: 5px 15px;
                border: 1px solid #555;
            }
        """)

        msg.exec_()

    def keyPressEvent(self, event):
        """Handle keyboard events."""
        key = event.key()

        # Handle number keys for color tagging
        if key == Qt.Key_0:
            # 0: Clear all tags
            path = self.image_files[self.current_index]
            self.clear_file_tags(path)
            return
        elif Qt.Key_1 <= key <= Qt.Key_7:
            # 1 through 7: Toggle color tags
            tag_number = key - Qt.Key_0
            path = self.image_files[self.current_index]
            self.set_file_tag(path, tag_number)
            return

        # Regular key handling
        if key == Qt.Key_Right:
            self.next_image()
        elif key == Qt.Key_Left:
            self.prev_image()
        elif key == Qt.Key_PageUp:
            self.first_image()
        elif key == Qt.Key_PageDown:
            self.last_image()
        elif key == Qt.Key_F:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            # Update display after fullscreen toggle
            QTimer.singleShot(100, self.update_display)
        elif key == Qt.Key_H:
            self.show_help()
        elif key == Qt.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
                QTimer.singleShot(100, self.update_display)
            else:
                self.close()
        elif key == Qt.Key_Q:
            self.close()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        """Handle window resize."""
        super().resizeEvent(event)
        self.update_display()


def collect_images(path):
    """Collect all image files from a file or directory."""
    path = Path(path)

    if not path.exists():
        print(f"Error: Path does not exist: {path}", file=sys.stderr)
        sys.exit(1)

    if path.is_file():
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            # If a file is provided, show all images in its directory
            parent_dir = path.parent
            all_images = [f for f in parent_dir.iterdir()
                         if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
            # Find the starting index
            try:
                start_index = all_images.index(path)
            except ValueError:
                start_index = 0
            return all_images, start_index
        else:
            print(f"Error: Not a supported image format: {path.suffix}", file=sys.stderr)
            sys.exit(1)

    elif path.is_dir():
        # Collect all images from directory
        images = [f for f in path.iterdir()
                 if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
        if not images:
            print(f"Error: No images found in directory: {path}", file=sys.stderr)
            sys.exit(1)
        return images, 0

    else:
        print(f"Error: Not a file or directory: {path}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    image_files, start_index = collect_images(input_path)

    print(f"Found {len(image_files)} images")

    app = QApplication(sys.argv)
    viewer = ImageViewer(image_files, start_index)
    viewer.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
