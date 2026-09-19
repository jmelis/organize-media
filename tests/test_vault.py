import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import vault


class VaultTests(unittest.TestCase):
    def test_walk_errors_fail_instead_of_reporting_success(self):
        def inaccessible(root, *, onerror):
            onerror(PermissionError('unreadable directory'))
            return iter(())

        with patch.object(vault.os, 'walk', side_effect=inaccessible):
            with self.assertRaises(PermissionError):
                list(vault.iter_files(Path('/unreadable')))

    def test_comparison_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            a.write_bytes(b'abc')
            self.assertEqual(vault.compare(a, b, False), 'missing')
            b.write_bytes(b'xyz')
            os.utime(a, (1000, 1000))
            os.utime(b, (1000, 1000))
            self.assertIsNone(vault.compare(a, b, False))
            self.assertEqual(vault.compare(a, b, True), 'content differs')
            b.write_bytes(b'abc')
            os.utime(b, (1000, 1000))
            self.assertIsNone(vault.compare(a, b, True))

    def test_rsync_never_deletes(self):
        for dry_run in (False, True):
            argv = vault.build_rsync(Path('/source'), Path('/target'), dry_run)
            self.assertFalse(any(arg.startswith('--del') for arg in argv))
            self.assertEqual('--dry-run' in argv, dry_run)
            self.assertIn('-rlt', argv)


if __name__ == '__main__':
    unittest.main()
