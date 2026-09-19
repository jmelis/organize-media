#!/usr/bin/env uv run
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyexiftool", "tqdm", "pymysql", "python-dotenv"]
# ///
"""Filesystem behavior tests. No real archive or database access."""
import contextlib
from datetime import datetime
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('archivist_wd', Path(__file__).with_name('archivist-wd.py'))
wd = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wd
spec.loader.exec_module(wd)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.drive = self.root / 'drive'
        for tree in ('Raws', 'Export', 'Other'):
            (self.drive / tree).mkdir(parents=True)
        self.patch = patch.object(wd, 'DRIVE', self.drive)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def media(self, name='img001.jpg', data=b'photo', tree='Export'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digest, sig = wd.hash_file(path)
        return wd.Media(path, tree, digest, sig)

    def run_ops(self, ops, dry=False, source_root=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return wd.execute(ops, dry, guard=lambda: None, source_root=source_root)

    def test_missing_raws_exits_before_diskutil(self):
        (self.drive / 'Raws').rmdir()
        with patch.object(wd.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'not mounted'):
                wd.require_drive()
            run.assert_not_called()

    def test_preview_confirmation_reuses_plan(self):
        ops = [('move', self.media(), self.drive / 'Export/img.jpg')]
        with patch.object(wd.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='y'), patch.object(wd, 'execute', return_value=0) as execute:
            self.assertEqual(wd.run_plan(ops, True), 0)
            self.assertEqual(execute.call_count, 2)
            self.assertIs(execute.call_args_list[0].args[0], ops)
            self.assertIs(execute.call_args_list[1].args[0], ops)
            self.assertTrue(execute.call_args_list[0].args[1])
            self.assertFalse(execute.call_args_list[1].args[1])

    def test_preview_defaults_to_no(self):
        ops = [('move', self.media(), self.drive / 'Export/img.jpg')]
        for answer in ('', 'n', 'yes', 'Y'):
            with self.subTest(answer=answer), patch.object(wd.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value=answer), patch.object(wd, 'execute', return_value=0) as execute, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(wd.run_plan(ops, True), 0)
                execute.assert_called_once_with(ops, True)

    def test_preview_eof_and_interrupt_cancel(self):
        ops = [('move', self.media(), self.drive / 'Export/img.jpg')]
        for error in (EOFError, KeyboardInterrupt):
            with self.subTest(error=error), patch.object(wd.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=error), patch.object(wd, 'execute', return_value=0) as execute, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(wd.run_plan(ops, True), 0)
                execute.assert_called_once_with(ops, True)

    def test_preview_noninteractive_never_prompts(self):
        ops = [('move', self.media(), self.drive / 'Export/img.jpg')]
        with patch.object(wd.sys.stdin, 'isatty', return_value=False), patch('builtins.input') as prompt, patch.object(wd, 'execute', return_value=0) as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(wd.run_plan(ops, True), 0)
            prompt.assert_not_called()
            execute.assert_called_once_with(ops, True)

    def test_directory_local_raw_routing_and_case(self):
        self.media('camera/IMG.RAF')
        self.media('camera/IMG.JPG')
        self.media('camera/exports/IMG.JPG')
        routes = {str(p.relative_to(self.source)): tree for p, tree in wd.discover(self.source)}
        self.assertEqual(routes, {'camera/IMG.RAF': 'Raws', 'camera/IMG.JPG': 'Raws', 'camera/exports/IMG.JPG': 'Export'})

    def test_parallel_matches_serial(self):
        for i in range(8):
            self.media(f'{i}.jpg', bytes([i]) * 100)
        entries = wd.discover(self.source)
        self.assertEqual(wd.hash_sources(entries, 1), wd.hash_sources(entries, 4))

    def test_collisions_existing_and_planned(self):
        a, b = self.media('a/img.jpg'), self.media('b/img.jpg', b'other')
        date = datetime(2025, 10, 26)
        directory = self.drive / 'Export/2025/2025-10-26'
        directory.mkdir(parents=True)
        (directory / 'img.jpg').write_bytes(b'existing')
        ops = wd.plan([a, b], {}, {a.path: date, b.path: date}, 'copy')
        self.assertEqual([op[2].name for op in ops], ['img_2.jpg', 'img_3.jpg'])
        self.assertEqual(self.run_ops(ops), 0)
        self.assertEqual((directory / 'img.jpg').read_bytes(), b'existing')
        self.assertEqual((directory / 'img_2.jpg').read_bytes(), b'photo')
        self.assertTrue(a.path.exists())

    def test_dry_run_has_no_mutations(self):
        m = self.media()
        ops = wd.plan([m], {}, {m.path: datetime(2025, 1, 2)}, 'move')
        before = sorted(self.root.rglob('*'))
        self.assertEqual(self.run_ops(ops, True), 0)
        self.assertEqual(before, sorted(self.root.rglob('*')))
        self.assertTrue(m.path.exists())

    def test_move_verified_copy(self):
        m = self.media()
        target = self.drive / 'Export/2025/2025-01-02/img.jpg'
        self.assertEqual(self.run_ops([('move', m, target)], source_root=self.source), 0)
        self.assertFalse(m.path.exists())
        self.assertEqual(target.read_bytes(), b'photo')

    def test_move_removes_empty_source_directories_but_not_source_root(self):
        m = self.media('nested/deeper/img.jpg')
        target = self.drive / 'Export/2025/2025-01-02/img.jpg'
        self.assertEqual(self.run_ops([('move', m, target)], source_root=self.source), 0)
        self.assertFalse(m.path.exists())
        self.assertFalse((self.source / 'nested/deeper').exists())
        self.assertFalse((self.source / 'nested').exists())
        self.assertTrue(self.source.exists())

    def test_delete_indexed_removes_empty_source_directories(self):
        m = self.media('nested/img.jpg')
        archived = self.drive / 'Other/existing.jpg'
        archived.write_bytes(b'photo')
        ops = wd.plan([m], {m.digest: [(archived, 5)]}, {}, 'delete-source')
        self.assertEqual(self.run_ops(ops, source_root=self.source), 0)
        self.assertFalse(m.path.exists())
        self.assertFalse((self.source / 'nested').exists())

    def test_dry_run_reports_but_does_not_remove_empty_directories(self):
        m = self.media('nested/img.jpg')
        target = self.drive / 'Export/2025/2025-01-02/img.jpg'
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(wd.execute([('move', m, target)], True,
                                        guard=lambda: None, source_root=self.source), 0)
        self.assertIn('WOULD remove-empty-dir:', output.getvalue())
        self.assertTrue((self.source / 'nested').exists())

    def test_concurrent_collision_never_overwrites_or_deletes(self):
        m = self.media()
        target = self.drive / 'Export/img.jpg'
        target.write_bytes(b'existing')
        self.assertEqual(self.run_ops([('move', m, target)]), 1)
        self.assertTrue(m.path.exists())
        self.assertEqual(target.read_bytes(), b'existing')
        self.assertFalse(list(target.parent.glob('.archivist-*')))

    def test_index_modes_and_delete_only_indexed(self):
        m, new = self.media(), self.media('new.jpg', b'new')
        archived = self.drive / 'Other/renamed.jpg'
        archived.write_bytes(b'photo')
        index = {m.digest: [(archived, 5)]}
        self.assertEqual(wd.plan([m], index, {}, 'copy')[0][0], 'skip-indexed')
        self.assertEqual(wd.plan([m], index, {}, 'move')[0][0], 'delete-indexed')
        ops = wd.plan([m, new], index, {}, 'delete-source')
        self.assertEqual([op[0] for op in ops], ['delete-indexed', 'keep-unindexed'])
        self.assertEqual(self.run_ops(ops, True), 0)
        self.assertTrue(m.path.exists())
        self.assertEqual(self.run_ops(ops), 0)
        self.assertFalse(m.path.exists())
        self.assertTrue(new.path.exists())
        self.assertTrue(archived.exists())

    def test_stale_database_cannot_delete(self):
        m = self.media()
        archived = self.drive / 'Export/img.jpg'
        archived.write_bytes(b'wrong')  # Same size; database still claims original hash.
        for mode in ('move', 'delete-source'):
            ops = wd.plan([m], {m.digest: [(archived, 5)]}, {}, mode)
            self.assertEqual(self.run_ops(ops), 1)
            self.assertTrue(m.path.exists())

    def test_move_deletes_indexed_and_moves_new(self):
        duplicate, new = self.media(), self.media('new.jpg', b'new')
        archived = self.drive / 'Other/existing.jpg'
        archived.write_bytes(b'photo')
        ops = wd.plan([duplicate, new], {duplicate.digest: [(archived, 5)]},
                      {new.path: datetime(2025, 1, 2)}, 'move')
        self.assertEqual([op[0] for op in ops], ['delete-indexed', 'move'])
        self.assertEqual(self.run_ops(ops, True), 0)
        self.assertTrue(duplicate.path.exists())
        self.assertTrue(new.path.exists())
        self.assertEqual(self.run_ops(ops), 0)
        self.assertFalse(duplicate.path.exists())
        self.assertFalse(new.path.exists())
        self.assertEqual(archived.read_bytes(), b'photo')
        self.assertEqual(ops[1][2].read_bytes(), b'new')

    def test_missing_indexed_file_is_not_duplicate(self):
        m = self.media()
        ops = wd.plan([m], {m.digest: [(self.drive / 'Export/missing.jpg', 5)]}, {}, 'delete-source')
        self.assertEqual(ops[0][0], 'keep-unindexed')

    def test_source_changed_after_hash_is_retained(self):
        m = self.media()
        m.path.write_bytes(b'edited')
        target = self.drive / 'Export/img.jpg'
        self.assertEqual(self.run_ops([('move', m, target)]), 1)
        self.assertTrue(m.path.exists())
        self.assertFalse(target.exists())

    def test_missing_date_is_error(self):
        m = self.media()
        ops = wd.plan([m], {}, {}, 'copy')
        self.assertEqual(self.run_ops(ops), 1)
        self.assertTrue(m.path.exists())

    def test_symlink_destination_rejected(self):
        m = self.media()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.drive / 'Export/2025').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_ops([('copy', m, self.drive / 'Export/2025/img.jpg')]), 1)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
