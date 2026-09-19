import contextlib
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import archivist


class DuplicateTests(unittest.TestCase):
    def run_import(self, source, target, **kwargs):
        with patch.object(archivist, 'extract_video_date', return_value=datetime(2026, 9, 19)):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return archivist.organize_media(
                    source, target, skip_flag_check=True, delete_duplicates=True, **kwargs
                )

    def test_in_place_import_preserves_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / '2026/2026-09-19/photo.mov'
            photo.parent.mkdir(parents=True)
            photo.write_bytes(b'only copy')
            self.assertEqual(self.run_import(root, root), 0)
            self.assertEqual(photo.read_bytes(), b'only copy')

    def test_delete_duplicates_preserves_conflicts_and_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source', Path(tmp) / 'target'
            source.mkdir()
            day = target / '2026/2026-09-19'
            day.mkdir(parents=True)
            for name in ('duplicate.mov', 'conflict.mov'):
                (source / name).write_bytes(b'source')
            (day / 'duplicate.mov').write_bytes(b'source')
            (day / 'conflict.mov').write_bytes(b'archive')
            self.assertEqual(self.run_import(source, target, dry_run=True), 1)
            self.assertTrue((source / 'duplicate.mov').exists())
            self.assertEqual(self.run_import(source, target), 1)
            self.assertFalse((source / 'duplicate.mov').exists())
            self.assertEqual((day / 'duplicate.mov').read_bytes(), b'source')
            self.assertEqual((source / 'conflict.mov').read_bytes(), b'source')
            self.assertEqual((day / 'conflict.mov').read_bytes(), b'archive')

    def test_image_comparison_and_byte_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            a.write_bytes(b'original')
            b.write_bytes(b'metadata edited')
            with patch.object(archivist.exiftool, 'ExifToolHelper'), patch.object(
                archivist, 'extract_image_hashes', return_value={a: 'same', b: 'same'}
            ):
                self.assertTrue(archivist.compare_pairs([(a, b)], 'image')[(a, b)])
            with patch.object(archivist.exiftool, 'ExifToolHelper'), patch.object(
                archivist, 'extract_image_hashes', return_value={}
            ):
                self.assertFalse(archivist.compare_pairs([(a, b)], 'image')[(a, b)])


if __name__ == '__main__':
    unittest.main()
