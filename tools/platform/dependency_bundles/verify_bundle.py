#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import posixpath
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def fail(message: str) -> None:
    raise AssertionError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check_archive(path: Path) -> list[str]:
    if not path.is_file():
        fail(f'archive missing: {path}')

    sha_file = path.with_name(path.name + '.sha256')
    if not sha_file.is_file():
        fail('detached .sha256 missing')
    digest, name = sha_file.read_text(encoding='utf-8').strip().split(None, 1)
    name = name.strip()
    if Path(name).name != name:
        fail('detached checksum contains a path')
    if name != path.name:
        fail('detached checksum basename mismatch')
    if sha256(path) != digest:
        fail('detached checksum mismatch')

    with tarfile.open(path, 'r:gz') as tf:
        members = tf.getmembers()
        roots = {m.name.split('/', 1)[0] for m in members if m.name}
        if len(roots) != 1:
            fail(f'archive must have one top-level root: {sorted(roots)}')
        root = next(iter(roots))

        for member in members:
            p = Path(member.name)
            if p.is_absolute() or '..' in p.parts:
                fail(f'unsafe archive path: {member.name}')
            if member.issym():
                target = member.linkname
                if target.startswith('/'):
                    fail(f'absolute symlink: {member.name} -> {target}')
                resolved = posixpath.normpath(
                    posixpath.join(posixpath.dirname(member.name), target)
                )
                if resolved != root and not resolved.startswith(root + '/'):
                    fail(f'escaping symlink: {member.name} -> {target}')
            elif member.islnk():
                target = member.linkname
                if target.startswith('/'):
                    fail(f'absolute hardlink: {member.name} -> {target}')
                resolved = posixpath.normpath(target)
                if resolved != root and not resolved.startswith(root + '/'):
                    fail(f'escaping hardlink: {member.name} -> {target}')
            if '/home/' in member.name or '/Users/' in member.name:
                fail(f'local workstation path leaked: {member.name}')
            if member.uname not in {'', 'root'} or member.gname not in {'', 'root'}:
                fail(
                    f'non-normalized owner metadata: {member.name}: '
                    f'{member.uname}:{member.gname}'
                )

        with tempfile.TemporaryDirectory(prefix='flare-bundle-verify-') as td:
            dest = Path(td)
            tf.extractall(dest, filter='data')
            extracted = dest / root
            required = [
                extracted / 'SHA256SUMS',
                extracted / 'restore.sh',
                extracted / 'README.md',
                extracted / 'profile.env',
                extracted / 'profile-toolchain.tsv',
                extracted / 'postconditions.tsv',
            ]
            for required_path in required:
                if not required_path.is_file():
                    fail(f'missing bundle contract file: {required_path.name}')

            manifest = extracted / 'SHA256SUMS'
            for line in manifest.read_text(encoding='utf-8').splitlines():
                if not line:
                    continue
                expected, rel = line.split('  ', 1)
                target = extracted / rel.removeprefix('./')
                if target.name == 'SHA256SUMS':
                    fail('SHA256SUMS must not hash itself')
                if not target.is_file():
                    fail(f'internal checksum target missing: {rel}')
                if sha256(target) != expected:
                    fail(f'internal checksum mismatch: {rel}')

            restore = extracted / 'restore.sh'
            result = subprocess.run(
                ['bash', '-n', str(restore)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                fail(f'restore.sh syntax error: {result.stderr}')

            text = restore.read_text(encoding='utf-8')
            required_restore_contract = [
                'target_preflight',
                'detect_tool_version',
                'validate_profile_versions',
                'build_candidate',
                'commit_current',
                'Single authoritative commit point',
                'sha256sum -c SHA256SUMS',
                '--frozen',
                '--offline',
                '$PROFILE_ROOT/current/activate.sh',
                'supported tool is missing',
            ]
            for token in required_restore_contract:
                if token not in text:
                    fail(f'restore contract token missing: {token}')
            if '$REPO/.venv' in text or 'VENV_LINK=' in text:
                fail('canonical restore must not mutate project .venv')
            if 'cat > "$FLARE/activate.sh"' in text:
                fail('canonical restore must not use global mutable activation')

    return [
        'detached checksum portable and valid',
        'single normalized top-level archive root',
        'archive paths and links are safe',
        'internal checksums exclude self and verify',
        'restore shell syntax valid',
        'transactional restore contract present',
        'project .venv is not mutated',
        'profile manifest and postconditions present',
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        findings = check_archive(args.archive.resolve())
    except (AssertionError, ValueError) as exc:
        print(f'BUNDLE CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    for finding in findings:
        print(f'PASS: {finding}')
    print('BUNDLE CONTRACT PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
