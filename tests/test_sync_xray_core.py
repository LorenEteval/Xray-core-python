import argparse
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import sync_xray_core as sync


COMMIT = 'a' * 40


def release(tag, published_at, *, prerelease=False, draft=False):
    return sync.UpstreamRelease(
        tag=tag,
        published_at=published_at,
        prerelease=prerelease,
        draft=draft,
    )


def provenance(tag='v26.1.1', published_at='2026-01-01T00:00:00Z'):
    return {
        'upstream_tag': tag,
        'upstream_published_at': published_at,
    }


def history(*tags):
    return {
        'schema': 1,
        'releases': [
            {
                'downstream_version': f'1.8.26.{index}',
                'upstream_commit': f'{index + 1:040x}',
                'upstream_tag': tag,
            }
            for index, tag in enumerate(tags)
        ],
    }


class VersionMappingTests(unittest.TestCase):
    def test_first_release_of_year_uses_base_version(self):
        self.assertEqual(sync.next_downstream_version(2026, []), '1.8.26')

    def test_sequence_uses_actual_downstream_versions(self):
        versions = ['1.8.26', 'v1.8.26.1', '1.8.25.20', 'unrelated']
        self.assertEqual(sync.next_downstream_version(2026, versions), '1.8.26.2')

    def test_year_rollover_resets_sequence(self):
        versions = ['1.8.26.19']
        self.assertEqual(sync.next_downstream_version(2027, versions), '1.8.27')
        self.assertEqual(
            sync.next_downstream_version(2027, versions + ['1.8.27']),
            '1.8.27.1',
        )


class ReleaseSelectionTests(unittest.TestCase):
    def test_selects_newest_stable_or_prerelease_and_ignores_drafts(self):
        releases = [
            release('v26.2.1', '2026-02-01T00:00:00Z'),
            release(
                'v26.2.2',
                '2026-02-02T00:00:00Z',
                prerelease=True,
            ),
            release(
                'v26.2.3',
                '2026-02-03T00:00:00Z',
                draft=True,
            ),
        ]
        selected = sync.select_release(releases, provenance(), history('v26.1.1'))
        self.assertEqual(selected.tag, 'v26.2.2')
        self.assertTrue(selected.prerelease)

    def test_same_release_is_idempotent(self):
        releases = [release('v26.1.1', '2026-01-01T00:00:00Z')]
        selected = sync.select_release(
            releases,
            provenance(),
            history('v26.1.1'),
            requested_tag='v26.1.1',
        )
        self.assertIsNone(selected)

    def test_manual_downgrade_is_rejected(self):
        releases = [release('v25.12.31', '2025-12-31T00:00:00Z')]
        with self.assertRaisesRegex(sync.SyncError, 'older upstream release'):
            sync.select_release(
                releases,
                provenance(),
                history('v26.1.1'),
                requested_tag='v25.12.31',
            )


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vendor = self.root / 'xray-go'
        (self.vendor / 'core').mkdir(parents=True)
        (self.vendor / 'binding').mkdir()
        (self.vendor / 'core' / 'upstream.go').write_bytes(b'upstream\n')
        (self.vendor / 'binding' / 'owned.go').write_bytes(b'binding\n')
        self.manifest = sync.build_manifest(
            self.vendor / 'core',
            upstream_tag='v26.1.1',
            upstream_commit=COMMIT,
        )
        self.manifest['files'] = {
            f'core/{name}': value for name, value in self.manifest['files'].items()
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_tree_passes(self):
        sync.verify_tree(
            self.vendor,
            self.manifest,
            ['binding/owned.go'],
        )

    def test_modified_upstream_file_fails(self):
        (self.vendor / 'core' / 'upstream.go').write_bytes(b'modified\n')
        with self.assertRaisesRegex(sync.SyncError, 'was modified'):
            sync.verify_tree(
                self.vendor,
                self.manifest,
                ['binding/owned.go'],
            )

    def test_unexpected_file_fails(self):
        (self.vendor / 'core' / 'unexpected.go').write_text(
            'package core\n', encoding='utf-8'
        )
        with self.assertRaisesRegex(sync.SyncError, 'unexpected'):
            sync.verify_tree(
                self.vendor,
                self.manifest,
                ['binding/owned.go'],
            )

    def test_binding_file_survives_vendor_replacement_byte_for_byte(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'core').mkdir()
        (source / 'core' / 'upstream.go').write_bytes(b'new upstream\n')
        owned = sync.snapshot_owned_files(self.vendor, ['binding/owned.go'])
        backup = self.root / 'backup'
        sync.replace_vendor_tree(self.vendor, source, owned, backup)
        self.assertEqual(
            (self.vendor / 'binding' / 'owned.go').read_bytes(),
            b'binding\n',
        )


class ProvenanceTests(unittest.TestCase):
    def test_duplicate_upstream_mapping_fails(self):
        duplicate = history('v26.1.1', 'v26.1.1')
        with self.assertRaisesRegex(sync.SyncError, 'mapped more than once'):
            sync.validate_release_history(duplicate)

    def test_release_notes_contain_required_correspondence(self):
        metadata = {
            'upstream_tag': 'v26.3.27',
            'upstream_commit': COMMIT,
            'upstream_prerelease': True,
        }
        notes = sync.release_notes(metadata)
        self.assertIn('Corresponds to Xray-core v26.3.27', notes)
        self.assertIn(COMMIT, notes)
        self.assertIn('prerelease', notes)

    def test_manifest_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            (source / 'b').write_bytes(b'b')
            (source / 'a').write_bytes(b'a')
            first = sync.build_manifest(
                source, upstream_tag='v26.1.1', upstream_commit=COMMIT
            )
            second = sync.build_manifest(
                source, upstream_tag='v26.1.1', upstream_commit=COMMIT
            )
            self.assertEqual(
                json.dumps(first, sort_keys=True),
                json.dumps(second, sort_keys=True),
            )

    def test_manifest_does_not_track_executable_mode(self):
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            (source / 'tool.cmd').write_bytes(b'command\n')
            manifest = sync.build_manifest(
                source, upstream_tag='v26.1.1', upstream_commit=COMMIT
            )

        self.assertNotIn('executable', manifest['files']['tool.cmd'])


class SynchronizationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vendor = self.root / 'xray-go'
        self.upstream_directory = self.root / 'upstream'
        (self.vendor / 'binding').mkdir(parents=True)
        self.upstream_directory.mkdir()
        (self.vendor / 'upstream.txt').write_bytes(b'old upstream\n')
        (self.vendor / 'binding' / 'owned.go').write_bytes(b'owned bytes\r\n')

        source = self.root / 'manifest-source'
        source.mkdir()
        (source / 'upstream.txt').write_bytes(b'old upstream\n')
        sync.write_json(
            self.upstream_directory / 'manifest.json',
            sync.build_manifest(
                source,
                upstream_tag='v26.1.1',
                upstream_commit='1' * 40,
            ),
        )
        sync.write_json(
            self.upstream_directory / 'ownership.json',
            {
                'schema': 1,
                'vendor_directory': 'xray-go',
                'binding_owned_files': ['binding/owned.go'],
                'patches': [],
            },
        )
        current = {
            'schema': 1,
            'downstream_version': '1.8.26.9',
            'upstream_commit': '1' * 40,
            'upstream_prerelease': False,
            'upstream_published_at': '2026-01-01T00:00:00Z',
            'upstream_repository': sync.UPSTREAM_REPOSITORY,
            'upstream_tag': 'v26.1.1',
        }
        sync.write_metadata(self.root, current)
        sync.write_json(
            self.upstream_directory / 'release-history.json',
            {
                'schema': 1,
                'releases': [
                    {
                        key: current[key]
                        for key in (
                            'downstream_version',
                            'upstream_commit',
                            'upstream_prerelease',
                            'upstream_published_at',
                            'upstream_tag',
                        )
                    }
                ],
            },
        )
        self.archive = self.make_archive()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def make_archive():
        buffer = io.BytesIO()
        content = b'new upstream\n'
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            root_info = tarfile.TarInfo('XTLS-Xray-core-new')
            root_info.type = tarfile.DIRTYPE
            archive.addfile(root_info)
            file_info = tarfile.TarInfo('XTLS-Xray-core-new/upstream.txt')
            file_info.size = len(content)
            file_info.mode = 0o644
            archive.addfile(file_info, io.BytesIO(content))
        return buffer.getvalue()

    def test_sync_preserves_binding_and_second_run_is_no_op(self):
        new_release = release(
            'v26.2.2',
            '2026-02-02T00:00:00Z',
            prerelease=True,
        )
        args = argparse.Namespace(
            root=self.root,
            tag=None,
            github_output=False,
        )
        with (
            mock.patch.object(
                sync,
                'current_release_data',
                side_effect=[(new_release, '2' * 40), (None, None)],
            ),
            mock.patch.object(sync, 'git_versions', return_value=['1.8.26.9']),
            mock.patch.object(sync, 'request_bytes', return_value=self.archive),
        ):
            sync.command_sync(args)
            first_state = {
                path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*')
                if path.is_file()
            }
            sync.command_sync(args)
            second_state = {
                path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*')
                if path.is_file()
            }

        self.assertEqual(first_state, second_state)
        self.assertEqual((self.root / 'VERSION').read_text().strip(), '1.8.26.10')
        self.assertEqual(
            (self.vendor / 'binding' / 'owned.go').read_bytes(),
            b'owned bytes\r\n',
        )
        self.assertEqual((self.vendor / 'upstream.txt').read_bytes(), b'new upstream\n')
        sync.verify_repository(self.root)

    def test_sync_rolls_back_vendor_and_metadata_on_final_verification_failure(self):
        new_release = release(
            'v26.2.2',
            '2026-02-02T00:00:00Z',
            prerelease=True,
        )
        args = argparse.Namespace(
            root=self.root,
            tag=None,
            github_output=False,
        )
        initial_state = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob('*')
            if path.is_file()
        }

        with (
            mock.patch.object(
                sync,
                'verify_repository',
                side_effect=[None, sync.SyncError('forced final verification failure')],
            ),
            mock.patch.object(
                sync,
                'current_release_data',
                return_value=(new_release, '2' * 40),
            ),
            mock.patch.object(sync, 'git_versions', return_value=['1.8.26.9']),
            mock.patch.object(sync, 'request_bytes', return_value=self.archive),
        ):
            with self.assertRaisesRegex(sync.SyncError, 'forced final verification'):
                sync.command_sync(args)

        final_state = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob('*')
            if path.is_file()
        }
        self.assertEqual(final_state, initial_state)


if __name__ == '__main__':
    unittest.main()
