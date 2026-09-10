#!/usr/bin/env python3
"""Synchronize the vendored Xray-core release and guard downstream releases."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


UPSTREAM_REPOSITORY = 'XTLS/Xray-core'
DOWNSTREAM_REPOSITORY = 'LorenEteval/Xray-core-python'
PYPI_PROJECT = 'Xray-core'
VERSION_PATTERN = re.compile(r'^v?1\.8\.(\d{2})(?:\.(\d+))?$')
SHA_PATTERN = re.compile(r'^[0-9a-f]{40}$')


class SyncError(RuntimeError):
    """A synchronization invariant was violated."""


@dataclasses.dataclass(frozen=True)
class UpstreamRelease:
    tag: str
    published_at: str
    prerelease: bool
    draft: bool = False

    @classmethod
    def from_api(cls, value: dict[str, Any]) -> 'UpstreamRelease':
        tag = value.get('tag_name')
        published_at = value.get('published_at')
        if not isinstance(tag, str) or not tag:
            raise SyncError('GitHub returned a release without a tag_name')
        if not isinstance(published_at, str) or not published_at:
            raise SyncError(f'GitHub release {tag} has no published_at value')
        parse_timestamp(published_at)
        return cls(
            tag=tag,
            published_at=published_at,
            prerelease=bool(value.get('prerelease')),
            draft=bool(value.get('draft')),
        )


def parse_timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise SyncError(f'Invalid GitHub timestamp: {value}') from error
    if parsed.tzinfo is None:
        raise SyncError(f'GitHub timestamp lacks a timezone: {value}')
    return parsed


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise SyncError(f'Required file is missing: {path}') from error
    except json.JSONDecodeError as error:
        raise SyncError(f'Invalid JSON in {path}: {error}') from error
    if not isinstance(value, dict):
        raise SyncError(f'Expected a JSON object in {path}')
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )


def read_text_value(path: Path) -> str:
    try:
        value = path.read_text(encoding='utf-8').strip()
    except FileNotFoundError as error:
        raise SyncError(f'Required file is missing: {path}') from error
    if not value:
        raise SyncError(f'Required file is empty: {path}')
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_relative_path(path: str) -> str:
    normalized = Path(path).as_posix()
    if normalized.startswith('/') or normalized == '..' or normalized.startswith('../'):
        raise SyncError(f'Path must stay inside the vendored tree: {path}')
    return normalized


def ownership_config(root: Path) -> dict[str, Any]:
    config = load_json(root / 'upstream' / 'ownership.json')
    if config.get('schema') != 1:
        raise SyncError('Unsupported ownership.json schema')
    if config.get('vendor_directory') != 'xray-go':
        raise SyncError('ownership.json must identify xray-go as the vendor directory')

    owned = config.get('binding_owned_files')
    patches = config.get('patches')
    if not isinstance(owned, list) or not all(isinstance(item, str) for item in owned):
        raise SyncError('binding_owned_files must be a list of paths')
    if not isinstance(patches, list):
        raise SyncError('patches must be a list')

    normalized = [normalize_relative_path(item) for item in owned]
    if len(set(normalized)) != len(normalized):
        raise SyncError('binding_owned_files contains duplicate paths')
    config['binding_owned_files'] = normalized
    return config


def iter_tree_entries(directory: Path) -> dict[str, Path]:
    entries: dict[str, Path] = {}
    for path in sorted(directory.rglob('*')):
        if path.is_dir():
            continue
        relative = path.relative_to(directory).as_posix()
        if relative == '.git' or relative.startswith('.git/'):
            continue
        entries[relative] = path
    return entries


def entry_record(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        return {
            'sha256': hashlib.sha256(os.readlink(path).encode()).hexdigest(),
            'type': 'symlink',
            'target': os.readlink(path),
        }
    return {
        'sha256': sha256_file(path),
        'type': 'file',
    }


def build_manifest(
    source: Path, *, upstream_tag: str, upstream_commit: str
) -> dict[str, Any]:
    if not SHA_PATTERN.fullmatch(upstream_commit):
        raise SyncError(f'Invalid upstream commit SHA: {upstream_commit}')
    files = {
        relative: entry_record(path)
        for relative, path in iter_tree_entries(source).items()
    }
    return {
        'schema': 1,
        'upstream_commit': upstream_commit,
        'upstream_repository': UPSTREAM_REPOSITORY,
        'upstream_tag': upstream_tag,
        'files': files,
    }


def expected_patched_hashes(root: Path) -> dict[str, str]:
    path = root / 'upstream' / 'patch-state.json'
    if not path.exists():
        return {}
    state = load_json(path)
    if state.get('schema') != 1 or not isinstance(state.get('files'), dict):
        raise SyncError('Invalid patch-state.json')
    result: dict[str, str] = {}
    for relative, digest in state['files'].items():
        relative = normalize_relative_path(relative)
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise SyncError(f'Invalid patched hash for {relative}')
        result[relative] = digest
    return result


def verify_tree(
    vendor: Path,
    manifest: dict[str, Any],
    owned_files: list[str],
    patched_hashes: dict[str, str] | None = None,
) -> None:
    files = manifest.get('files')
    if manifest.get('schema') != 1 or not isinstance(files, dict):
        raise SyncError('Invalid upstream manifest schema')

    patched_hashes = patched_hashes or {}
    expected_paths = set(files) | set(owned_files)
    actual_entries = iter_tree_entries(vendor)
    actual_paths = set(actual_entries)

    missing = sorted(expected_paths - actual_paths)
    unexpected = sorted(actual_paths - expected_paths)
    if missing or unexpected:
        details = []
        if missing:
            details.append('missing: ' + ', '.join(missing))
        if unexpected:
            details.append('unexpected: ' + ', '.join(unexpected))
        raise SyncError('Vendored tree ownership mismatch (' + '; '.join(details) + ')')

    for relative, expected in files.items():
        path = actual_entries[relative]
        actual = entry_record(path)
        expected_type = expected.get('type')
        if actual.get('type') != expected_type:
            raise SyncError(f'Vendored entry type changed: {relative}')

        expected_hash = patched_hashes.get(relative, expected.get('sha256'))
        if actual.get('sha256') != expected_hash:
            raise SyncError(f'Vendored upstream file was modified: {relative}')

    for relative in owned_files:
        if relative in files:
            raise SyncError(f'Binding-owned path collides with upstream: {relative}')

    unknown_patch_targets = set(patched_hashes) - set(files)
    if unknown_patch_targets:
        raise SyncError(
            'Patch state names non-upstream files: '
            + ', '.join(sorted(unknown_patch_targets))
        )


def validate_release_history(history: dict[str, Any]) -> None:
    if history.get('schema') != 1 or not isinstance(history.get('releases'), list):
        raise SyncError('Invalid release-history.json')
    tags: set[str] = set()
    versions: set[str] = set()
    commits: set[str] = set()
    for entry in history['releases']:
        if not isinstance(entry, dict):
            raise SyncError('release-history.json entries must be objects')
        tag = entry.get('upstream_tag')
        version = entry.get('downstream_version')
        commit = entry.get('upstream_commit')
        if not isinstance(tag, str) or not isinstance(version, str):
            raise SyncError('Release history entry lacks a tag or version')
        if not isinstance(commit, str) or not SHA_PATTERN.fullmatch(commit):
            raise SyncError(f'Release history has an invalid commit for {tag}')
        if tag in tags:
            raise SyncError(f'Upstream release is mapped more than once: {tag}')
        if version in versions:
            raise SyncError(f'Downstream version is mapped more than once: {version}')
        if commit in commits:
            raise SyncError(f'Upstream commit is mapped more than once: {commit}')
        tags.add(tag)
        versions.add(version)
        commits.add(commit)


def verify_repository(root: Path) -> None:
    ownership = ownership_config(root)
    manifest = load_json(root / 'upstream' / 'manifest.json')
    provenance = load_json(root / 'upstream' / 'provenance.json')
    history = load_json(root / 'upstream' / 'release-history.json')
    validate_release_history(history)

    if manifest.get('upstream_repository') != UPSTREAM_REPOSITORY:
        raise SyncError('Manifest has the wrong upstream repository')
    for field in ('upstream_tag', 'upstream_commit'):
        if manifest.get(field) != provenance.get(field):
            raise SyncError(f'Manifest and provenance disagree on {field}')

    expected_text = {
        'VERSION': provenance.get('downstream_version'),
        'UPSTREAM_VERSION': provenance.get('upstream_tag'),
        'UPSTREAM_COMMIT': provenance.get('upstream_commit'),
        'UPSTREAM_PRERELEASE': str(provenance.get('upstream_prerelease')).lower(),
        'UPSTREAM_RELEASE_DATE': provenance.get('upstream_published_at'),
    }
    for filename, expected in expected_text.items():
        if (
            not isinstance(expected, str)
            or read_text_value(root / filename) != expected
        ):
            raise SyncError(f'{filename} disagrees with upstream/provenance.json')

    current_entries = [
        entry
        for entry in history['releases']
        if entry.get('downstream_version') == provenance.get('downstream_version')
    ]
    if len(current_entries) != 1:
        raise SyncError('Current provenance must have exactly one history entry')
    for field in (
        'upstream_tag',
        'upstream_commit',
        'upstream_prerelease',
        'upstream_published_at',
    ):
        if current_entries[0].get(field) != provenance.get(field):
            raise SyncError(f'Current history and provenance disagree on {field}')

    verify_tree(
        root / ownership['vendor_directory'],
        manifest,
        ownership['binding_owned_files'],
        expected_patched_hashes(root),
    )


def parse_downstream_version(value: str) -> tuple[int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        raise SyncError(f'Unsupported downstream version: {value}')
    year = int(match.group(1))
    sequence = int(match.group(2)) if match.group(2) is not None else 0
    return year, sequence


def next_downstream_version(upstream_year: int, versions: list[str]) -> str:
    year = upstream_year % 100
    sequences = []
    for version in versions:
        try:
            version_year, sequence = parse_downstream_version(version)
        except SyncError:
            continue
        if version_year == year:
            sequences.append(sequence)
    base = f'1.8.{year:02d}'
    return base if not sequences else f'{base}.{max(sequences) + 1}'


def select_release(
    releases: list[UpstreamRelease],
    provenance: dict[str, Any],
    history: dict[str, Any],
    requested_tag: str | None = None,
) -> UpstreamRelease | None:
    validate_release_history(history)
    eligible = [release for release in releases if not release.draft]
    by_tag = {release.tag: release for release in eligible}
    if len(by_tag) != len(eligible):
        raise SyncError('GitHub returned duplicate upstream release tags')

    current_tag = provenance.get('upstream_tag')
    current_published_at = provenance.get('upstream_published_at')
    if not isinstance(current_tag, str) or not isinstance(current_published_at, str):
        raise SyncError('Current provenance lacks its upstream release information')
    current_time = parse_timestamp(current_published_at)
    synchronized = {entry['upstream_tag'] for entry in history['releases']}

    if requested_tag:
        if requested_tag == current_tag or requested_tag in synchronized:
            return None
        try:
            release = by_tag[requested_tag]
        except KeyError as error:
            raise SyncError(
                f'{requested_tag} is not a published, non-draft GitHub Release'
            ) from error
        if parse_timestamp(release.published_at) <= current_time:
            raise SyncError(
                f'Refusing to synchronize older upstream release {requested_tag}'
            )
        return release

    candidates = [
        release
        for release in eligible
        if release.tag not in synchronized
        and parse_timestamp(release.published_at) > current_time
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda release: parse_timestamp(release.published_at))


def github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'Xray-core-python-upstream-sync',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def request_bytes(
    url: str, *, token: str | None = None, allow_not_found: bool = False
) -> bytes | None:
    request = urllib.request.Request(url, headers=github_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if allow_not_found and error.code == 404:
            return None
        raise SyncError(f'HTTP {error.code} from {url}') from error
    except urllib.error.URLError as error:
        raise SyncError(f'Unable to request {url}: {error.reason}') from error


def request_json(
    url: str, *, token: str | None = None, allow_not_found: bool = False
) -> Any:
    data = request_bytes(url, token=token, allow_not_found=allow_not_found)
    if data is None:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError as error:
        raise SyncError(f'Invalid JSON returned by {url}') from error


def list_github_releases(repository: str, token: str | None) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for page in range(1, 101):
        url = (
            f'https://api.github.com/repos/{repository}/releases'
            f'?per_page=100&page={page}'
        )
        values = request_json(url, token=token)
        if not isinstance(values, list):
            raise SyncError(f'GitHub releases response is not a list: {repository}')
        if not all(isinstance(value, dict) for value in values):
            raise SyncError(
                f'GitHub releases response has invalid entries: {repository}'
            )
        releases.extend(values)
        if len(values) < 100:
            return releases
    raise SyncError(f'GitHub release pagination exceeded 100 pages: {repository}')


def resolve_tag_commit(repository: str, tag: str, token: str | None) -> str:
    encoded_tag = urllib.parse.quote(tag, safe='')
    value = request_json(
        f'https://api.github.com/repos/{repository}/git/ref/tags/{encoded_tag}',
        token=token,
    )
    if not isinstance(value, dict) or not isinstance(value.get('object'), dict):
        raise SyncError(f'Invalid GitHub tag response for {tag}')
    tag_object = value['object']
    for _ in range(10):
        object_type = tag_object.get('type')
        sha = tag_object.get('sha')
        if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
            raise SyncError(f'Invalid Git object SHA for {tag}')
        if object_type == 'commit':
            return sha
        if object_type != 'tag':
            raise SyncError(f'Unexpected Git object type for {tag}: {object_type}')
        tag_value = request_json(
            f'https://api.github.com/repos/{repository}/git/tags/{sha}', token=token
        )
        if not isinstance(tag_value, dict) or not isinstance(
            tag_value.get('object'), dict
        ):
            raise SyncError(f'Invalid annotated tag response for {tag}')
        tag_object = tag_value['object']
    raise SyncError(f'Annotated tag chain is too deep for {tag}')


def token_from_environment() -> str | None:
    return os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')


def current_release_data(
    root: Path, requested_tag: str | None
) -> tuple[UpstreamRelease | None, str | None]:
    provenance = load_json(root / 'upstream' / 'provenance.json')
    history = load_json(root / 'upstream' / 'release-history.json')
    token = token_from_environment()
    releases = [
        UpstreamRelease.from_api(value)
        for value in list_github_releases(UPSTREAM_REPOSITORY, token)
    ]
    release = select_release(releases, provenance, history, requested_tag)
    if release is None:
        return None, None
    return release, resolve_tag_commit(UPSTREAM_REPOSITORY, release.tag, token)


def git_versions(root: Path) -> list[str]:
    result = subprocess.run(
        ['git', 'tag', '--list', 'v1.8.*'],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().removeprefix('v') for line in result.stdout.splitlines()]


def safe_extract_github_archive(data: bytes, destination: Path) -> Path:
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        top_levels = {
            Path(member.name).parts[0] for member in members if Path(member.name).parts
        }
        if len(top_levels) != 1:
            raise SyncError('GitHub archive does not have exactly one root directory')
        archive.extractall(destination, filter='data')
    extracted = destination / next(iter(top_levels))
    if not extracted.is_dir():
        raise SyncError('GitHub archive root was not extracted')
    return extracted


def snapshot_owned_files(vendor: Path, owned_files: list[str]) -> dict[str, bytes]:
    snapshots: dict[str, bytes] = {}
    for relative in owned_files:
        path = vendor / relative
        if not path.is_file():
            raise SyncError(
                f'Binding-owned file is missing before synchronization: {relative}'
            )
        snapshots[relative] = path.read_bytes()
    return snapshots


def apply_patches(root: Path, source: Path, patches: list[Any]) -> dict[str, str]:
    if not patches:
        return {}
    subprocess.run(['git', 'init', '--quiet'], cwd=source, check=True)
    subprocess.run(['git', 'config', 'core.autocrlf', 'false'], cwd=source, check=True)
    patch_targets: set[str] = set()
    try:
        for item in patches:
            if not isinstance(item, dict):
                raise SyncError('Each patch declaration must be an object')
            patch_path = item.get('path')
            targets = item.get('target_files')
            if not isinstance(patch_path, str) or not isinstance(targets, list):
                raise SyncError('Patch declarations require path and target_files')
            patch = root / normalize_relative_path(patch_path)
            if not patch.is_file():
                raise SyncError(f'Declared patch is missing: {patch_path}')
            normalized_targets = [normalize_relative_path(target) for target in targets]
            patch_targets.update(normalized_targets)
            subprocess.run(
                ['git', 'apply', '--check', str(patch.resolve())],
                cwd=source,
                check=True,
            )
            subprocess.run(
                ['git', 'apply', str(patch.resolve())], cwd=source, check=True
            )
    except subprocess.CalledProcessError as error:
        raise SyncError(
            'An explicit upstream patch no longer applies cleanly'
        ) from error
    finally:
        shutil.rmtree(source / '.git', ignore_errors=True)

    patched_hashes: dict[str, str] = {}
    for relative in sorted(patch_targets):
        target = source / relative
        if not target.is_file():
            raise SyncError(f'Patch target is missing after application: {relative}')
        patched_hashes[relative] = sha256_file(target)
    return patched_hashes


def replace_vendor_tree(
    vendor: Path, source: Path, owned_snapshots: dict[str, bytes], backup: Path
) -> None:
    if backup.exists():
        raise SyncError(f'Vendor backup already exists: {backup}')
    vendor.rename(backup)
    try:
        shutil.copytree(
            source,
            vendor,
            symlinks=True,
            ignore=shutil.ignore_patterns('.git'),
        )
        for relative, content in owned_snapshots.items():
            target = vendor / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for relative, content in owned_snapshots.items():
            if (vendor / relative).read_bytes() != content:
                raise SyncError(f'Binding-owned file changed during sync: {relative}')
    except Exception:
        if vendor.exists():
            shutil.rmtree(vendor)
        backup.rename(vendor)
        raise


def metadata_for_release(
    release: UpstreamRelease, commit: str, downstream_version: str
) -> dict[str, Any]:
    return {
        'schema': 1,
        'downstream_version': downstream_version,
        'upstream_commit': commit,
        'upstream_prerelease': release.prerelease,
        'upstream_published_at': release.published_at,
        'upstream_repository': UPSTREAM_REPOSITORY,
        'upstream_tag': release.tag,
    }


def write_metadata(root: Path, provenance: dict[str, Any]) -> None:
    write_json(root / 'upstream' / 'provenance.json', provenance)
    text_values = {
        'VERSION': provenance['downstream_version'],
        'UPSTREAM_VERSION': provenance['upstream_tag'],
        'UPSTREAM_COMMIT': provenance['upstream_commit'],
        'UPSTREAM_PRERELEASE': str(provenance['upstream_prerelease']).lower(),
        'UPSTREAM_RELEASE_DATE': provenance['upstream_published_at'],
    }
    for filename, value in text_values.items():
        (root / filename).write_text(str(value) + '\n', encoding='utf-8')


def snapshot_repository_metadata(root: Path) -> dict[str, bytes | None]:
    relative_paths = (
        'VERSION',
        'UPSTREAM_VERSION',
        'UPSTREAM_COMMIT',
        'UPSTREAM_PRERELEASE',
        'UPSTREAM_RELEASE_DATE',
        'upstream/manifest.json',
        'upstream/patch-state.json',
        'upstream/provenance.json',
        'upstream/release-history.json',
    )
    return {
        relative: (
            (root / relative).read_bytes() if (root / relative).is_file() else None
        )
        for relative in relative_paths
    }


def restore_repository_metadata(root: Path, snapshots: dict[str, bytes | None]) -> None:
    for relative, content in snapshots.items():
        path = root / relative
        if content is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def result_values(
    *,
    changed: bool,
    release: UpstreamRelease | None = None,
    commit: str | None = None,
    downstream_version: str | None = None,
) -> dict[str, str]:
    result = {'changed': str(changed).lower()}
    if release is not None and commit is not None:
        result.update(
            {
                'upstream_tag': release.tag,
                'upstream_commit': commit,
                'upstream_prerelease': str(release.prerelease).lower(),
            }
        )
    if downstream_version is not None:
        result['downstream_version'] = downstream_version
        result['release_tag'] = f'v{downstream_version}'
    return result


def emit_result(result: dict[str, str], github_output: bool) -> None:
    print(json.dumps(result, sort_keys=True))
    if github_output:
        output_path = os.environ.get('GITHUB_OUTPUT')
        if not output_path:
            raise SyncError('--github-output requires GITHUB_OUTPUT')
        with Path(output_path).open('a', encoding='utf-8') as output:
            for key, value in result.items():
                output.write(f'{key}={value}\n')


def command_verify(args: argparse.Namespace) -> None:
    verify_repository(args.root)
    print('Vendored Xray-core tree and provenance are valid.')


def command_check(args: argparse.Namespace) -> None:
    verify_repository(args.root)
    release, commit = current_release_data(args.root, args.tag)
    if release is None:
        emit_result(result_values(changed=False), args.github_output)
        return
    emit_result(
        result_values(changed=True, release=release, commit=commit),
        args.github_output,
    )


def command_sync(args: argparse.Namespace) -> None:
    root = args.root
    verify_repository(root)
    release, commit = current_release_data(root, args.tag)
    if release is None or commit is None:
        emit_result(result_values(changed=False), args.github_output)
        return

    ownership = ownership_config(root)
    history = load_json(root / 'upstream' / 'release-history.json')
    validate_release_history(history)
    versions = git_versions(root) + [
        entry['downstream_version'] for entry in history['releases']
    ]
    release_year = parse_timestamp(release.published_at).year
    downstream_version = next_downstream_version(release_year, versions)
    if any(
        entry['upstream_tag'] == release.tag
        or entry['upstream_commit'] == commit
        or entry['downstream_version'] == downstream_version
        for entry in history['releases']
    ):
        raise SyncError('The proposed upstream/downstream mapping is not one-to-one')

    token = token_from_environment()
    archive_url = f'https://api.github.com/repos/{UPSTREAM_REPOSITORY}/tarball/{commit}'
    archive_data = request_bytes(archive_url, token=token)
    if archive_data is None:
        raise SyncError(f'Unable to download upstream archive for {release.tag}')

    vendor = root / ownership['vendor_directory']
    owned_snapshots = snapshot_owned_files(vendor, ownership['binding_owned_files'])
    metadata_snapshots = snapshot_repository_metadata(root)
    with tempfile.TemporaryDirectory(prefix='.xray-sync-', dir=root) as temp_name:
        temp = Path(temp_name)
        source = safe_extract_github_archive(archive_data, temp / 'archive')
        manifest = build_manifest(
            source, upstream_tag=release.tag, upstream_commit=commit
        )
        patched_hashes = apply_patches(root, source, ownership['patches'])
        verify_tree(
            source,
            manifest,
            [],
            patched_hashes,
        )

        backup = temp / 'vendor-backup'
        try:
            replace_vendor_tree(vendor, source, owned_snapshots, backup)
            verify_tree(
                vendor,
                manifest,
                ownership['binding_owned_files'],
                patched_hashes,
            )

            write_json(root / 'upstream' / 'manifest.json', manifest)
            patch_state_path = root / 'upstream' / 'patch-state.json'
            if patched_hashes:
                write_json(patch_state_path, {'schema': 1, 'files': patched_hashes})
            elif patch_state_path.exists():
                patch_state_path.unlink()

            provenance = metadata_for_release(release, commit, downstream_version)
            write_metadata(root, provenance)
            history['releases'].append(
                {
                    key: provenance[key]
                    for key in (
                        'downstream_version',
                        'upstream_commit',
                        'upstream_prerelease',
                        'upstream_published_at',
                        'upstream_tag',
                    )
                }
            )
            write_json(root / 'upstream' / 'release-history.json', history)
            verify_repository(root)
        except Exception:
            if backup.exists():
                if vendor.exists():
                    shutil.rmtree(vendor)
                backup.rename(vendor)
            restore_repository_metadata(root, metadata_snapshots)
            raise
        else:
            shutil.rmtree(backup)

    emit_result(
        result_values(
            changed=True,
            release=release,
            commit=commit,
            downstream_version=downstream_version,
        ),
        args.github_output,
    )


def url_exists(url: str, token: str | None = None) -> bool:
    return request_bytes(url, token=token, allow_not_found=True) is not None


def matching_release_tag_exists(
    root: Path, downstream_tag: str, upstream_tag: str
) -> bool:
    tag_ref = f'refs/tags/{downstream_tag}'
    local_tags = subprocess.run(
        ['git', 'tag', '--list', downstream_tag],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if downstream_tag not in local_tags:
        return False

    tag_type = subprocess.run(
        ['git', 'cat-file', '-t', tag_ref],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tag_type != 'tag':
        raise SyncError(f'Existing Git tag is not annotated: {downstream_tag}')

    tag_commit = subprocess.run(
        ['git', 'rev-list', '-n', '1', tag_ref],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    head_commit = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tag_commit != head_commit:
        raise SyncError(
            f'Existing Git tag {downstream_tag} points to {tag_commit}, '
            f'not release commit {head_commit}'
        )

    tag_subject = subprocess.run(
        ['git', 'for-each-ref', '--format=%(contents:subject)', tag_ref],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected_subject = f'Corresponds to Xray-core {upstream_tag}'
    if tag_subject != expected_subject:
        raise SyncError(
            f'Existing Git tag {downstream_tag} has unexpected annotation'
        )
    return True


def command_guard_release(args: argparse.Namespace) -> None:
    root = args.root
    verify_repository(root)
    provenance = load_json(root / 'upstream' / 'provenance.json')
    downstream_tag = args.downstream_tag or f"v{provenance['downstream_version']}"
    upstream_tag = args.upstream_tag or provenance['upstream_tag']
    if downstream_tag != f"v{provenance['downstream_version']}":
        raise SyncError('Requested downstream tag disagrees with provenance')
    if upstream_tag != provenance['upstream_tag']:
        raise SyncError('Requested upstream tag disagrees with provenance')

    existing_tag = matching_release_tag_exists(root, downstream_tag, upstream_tag)

    token = token_from_environment()
    downstream_repository = os.environ.get('GITHUB_REPOSITORY', DOWNSTREAM_REPOSITORY)
    encoded_downstream_tag = urllib.parse.quote(downstream_tag, safe='')
    remote_tag_exists = url_exists(
        f'https://api.github.com/repos/{downstream_repository}/git/ref/tags/'
        f'{encoded_downstream_tag}',
        token,
    )
    if remote_tag_exists and not existing_tag:
        raise SyncError(f'Remote Git tag already exists: {downstream_tag}')
    if url_exists(
        f'https://api.github.com/repos/{downstream_repository}/releases/tags/'
        f'{encoded_downstream_tag}',
        token,
    ):
        raise SyncError(f'GitHub Release already exists: {downstream_tag}')
    if url_exists(
        f'https://pypi.org/pypi/{urllib.parse.quote(PYPI_PROJECT, safe="")}/'
        f'{urllib.parse.quote(provenance["downstream_version"], safe="")}/json'
    ):
        raise SyncError(
            f'PyPI version already exists: {provenance["downstream_version"]}'
        )

    correspondence = f'Corresponds to Xray-core {upstream_tag}'
    for release in list_github_releases(downstream_repository, token):
        if correspondence in str(release.get('body') or ''):
            raise SyncError(
                f'Upstream release is already mapped by a GitHub Release: {upstream_tag}'
            )
    if existing_tag:
        print(f'Reusing existing release tag {downstream_tag}.')
    else:
        print(
            f'Release state is clear for {downstream_tag} and upstream {upstream_tag}.'
        )


def release_notes(provenance: dict[str, Any]) -> str:
    return f"Corresponds to Xray-core {provenance['upstream_tag']}\n"


def command_release_notes(args: argparse.Namespace) -> None:
    verify_repository(args.root)
    notes = release_notes(load_json(args.root / 'upstream' / 'provenance.json'))
    if args.output:
        args.output.write_text(notes, encoding='utf-8')
    else:
        print(notes, end='')


def command_bootstrap_manifest(args: argparse.Namespace) -> None:
    provenance = load_json(args.root / 'upstream' / 'provenance.json')
    manifest = build_manifest(
        args.source,
        upstream_tag=provenance['upstream_tag'],
        upstream_commit=provenance['upstream_commit'],
    )
    write_json(args.root / 'upstream' / 'manifest.json', manifest)
    print(f"Recorded {len(manifest['files'])} exact upstream files.")


def command_bootstrap_vendor(args: argparse.Namespace) -> None:
    ownership = ownership_config(args.root)
    manifest = load_json(args.root / 'upstream' / 'manifest.json')
    vendor = args.root / ownership['vendor_directory']
    owned_snapshots = snapshot_owned_files(vendor, ownership['binding_owned_files'])
    with tempfile.TemporaryDirectory(
        prefix='.xray-bootstrap-', dir=args.root
    ) as temp_name:
        backup = Path(temp_name) / 'vendor-backup'
        replace_vendor_tree(vendor, args.source, owned_snapshots, backup)
        verify_tree(
            vendor,
            manifest,
            ownership['binding_owned_files'],
            expected_patched_hashes(args.root),
        )
        shutil.rmtree(backup)
    print('Rebuilt xray-go from the exact upstream tree and binding-owned files.')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--root', type=Path, default=Path(__file__).resolve().parents[1]
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    verify_parser = subparsers.add_parser('verify')
    verify_parser.set_defaults(func=command_verify)

    for name, function in (('check', command_check), ('sync', command_sync)):
        command_parser = subparsers.add_parser(name)
        command_parser.add_argument('--tag')
        command_parser.add_argument('--github-output', action='store_true')
        command_parser.set_defaults(func=function)

    guard_parser = subparsers.add_parser('guard-release')
    guard_parser.add_argument('--downstream-tag')
    guard_parser.add_argument('--upstream-tag')
    guard_parser.set_defaults(func=command_guard_release)

    notes_parser = subparsers.add_parser('release-notes')
    notes_parser.add_argument('--output', type=Path)
    notes_parser.set_defaults(func=command_release_notes)

    manifest_parser = subparsers.add_parser('bootstrap-manifest')
    manifest_parser.add_argument('--source', type=Path, required=True)
    manifest_parser.set_defaults(func=command_bootstrap_manifest)

    vendor_parser = subparsers.add_parser('bootstrap-vendor')
    vendor_parser.add_argument('--source', type=Path, required=True)
    vendor_parser.set_defaults(func=command_bootstrap_vendor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    if hasattr(args, 'source'):
        args.source = args.source.resolve()
    if hasattr(args, 'output') and args.output is not None:
        args.output = args.output.resolve()
    try:
        args.func(args)
    except SyncError as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    sys.exit(main())
