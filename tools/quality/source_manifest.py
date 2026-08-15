import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from tools.canonical_paths import CanonicalPathError, canonical_relative_posix_path
from tools.project_state.git import run_git
from tools.project_state.json_codec import canonical_json_bytes
from tools.project_state.model import JSONValue

type ModelTuple[T] = Annotated[tuple[T, ...], Field(strict=False)]
type SourceKind = Literal["file", "symlink"]


class ManifestEntryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: StrictStr
    kind: SourceKind
    mode: StrictInt
    bytes: StrictInt
    sha256: StrictStr


class ManifestDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[2]
    hash_algorithm: Literal["sha256"]
    manifest_sha256: StrictStr
    files: ModelTuple[ManifestEntryModel]


@dataclass(frozen=True, slots=True)
class SourceManifest:
    document: ManifestDocumentModel
    encoded: bytes

    @property
    def sha256(self) -> str:
        return self.document.manifest_sha256


class SourceManifestError(RuntimeError):
    pass


def build_git_source_manifest(repo: Path) -> SourceManifest:
    result = run_git(
        repo,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SourceManifestError(f"git ls-files failed: {detail}")
    paths = tuple(
        path
        for raw_path in result.stdout.split(b"\0")
        if raw_path
        for path in (raw_path.decode("utf-8", "strict"),)
        if (repo / path).is_file() or (repo / path).is_symlink()
    )
    return build_source_manifest(repo, paths)


def build_directory_source_manifest(root: Path) -> SourceManifest:
    paths = tuple(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    )
    return build_source_manifest(root, paths)


def build_source_manifest(root: Path, paths: tuple[str, ...]) -> SourceManifest:
    if len(set(paths)) != len(paths):
        raise SourceManifestError("source paths must be unique")
    try:
        paths = tuple(
            canonical_relative_posix_path(path, label="source path") for path in paths
        )
    except CanonicalPathError as error:
        raise SourceManifestError(str(error)) from error
    entries = tuple(
        _manifest_entry(root, path) for path in sorted(paths, key=str.encode)
    )
    identity: dict[str, JSONValue] = {
        "files": [_entry_json(entry) for entry in entries],
        "hash_algorithm": "sha256",
        "version": 2,
    }
    manifest_sha256 = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    document_value: dict[str, JSONValue] = {
        **identity,
        "manifest_sha256": manifest_sha256,
    }
    encoded = canonical_json_bytes(document_value)
    document = ManifestDocumentModel.model_validate_json(encoded)
    return SourceManifest(document, encoded)


def parse_source_manifest(raw: bytes) -> SourceManifest:
    document = ManifestDocumentModel.model_validate_json(raw)
    paths = tuple(entry.path for entry in document.files)
    if paths != tuple(sorted(paths, key=str.encode)) or len(set(paths)) != len(paths):
        raise SourceManifestError("source manifest paths are not sorted and unique")
    for entry in document.files:
        try:
            canonical_relative_posix_path(entry.path, label="source path")
        except CanonicalPathError as error:
            raise SourceManifestError(str(error)) from error
        if entry.bytes < 0 or not 0 <= entry.mode <= 0o7777:
            raise SourceManifestError(f"invalid source manifest entry: {entry.path}")
        if len(entry.sha256) != 64 or any(
            digit not in "0123456789abcdef" for digit in entry.sha256
        ):
            raise SourceManifestError(f"invalid source digest: {entry.path}")
    identity: dict[str, JSONValue] = {
        "files": [_entry_json(entry) for entry in document.files],
        "hash_algorithm": document.hash_algorithm,
        "version": document.version,
    }
    observed = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    if observed != document.manifest_sha256:
        raise SourceManifestError(
            f"source manifest digest mismatch: expected={document.manifest_sha256}, observed={observed}"
        )
    encoded = canonical_json_bytes({**identity, "manifest_sha256": observed})
    if raw != encoded:
        raise SourceManifestError("source manifest is not canonical JSON")
    return SourceManifest(document, encoded)


def main(
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
    repo: Annotated[Path, typer.Option("--repo", file_okay=False)] = Path("."),
    directory: Annotated[
        Path | None,
        typer.Option("--directory", file_okay=False),
    ] = None,
) -> None:
    manifest = (
        build_directory_source_manifest(directory)
        if directory is not None
        else build_git_source_manifest(repo)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(manifest.encoded)
    typer.echo(manifest.sha256)


def _manifest_entry(root: Path, relative_path: str) -> ManifestEntryModel:
    path = root / relative_path
    metadata = path.lstat()
    if path.is_symlink():
        kind: SourceKind = "symlink"
        raw = read_confined_symlink_target(root, path).encode("utf-8")
    else:
        kind = "file"
        raw = path.read_bytes()
    return ManifestEntryModel(
        path=relative_path,
        kind=kind,
        mode=stat.S_IMODE(metadata.st_mode),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def read_confined_symlink_target(root: Path, path: Path) -> str:
    try:
        target = os.readlink(path)
        root_absolute = root.resolve(strict=True)
        link_relative = path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise SourceManifestError(f"cannot inspect source symlink: {path}") from error
    if Path(target).is_absolute():
        raise SourceManifestError(
            f"absolute source symlink target rejected: {link_relative}"
        )

    parts = list(link_relative.parent.parts)
    for part in Path(target).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise SourceManifestError(
                    f"source symlink target escapes root: {link_relative}"
                )
            parts.pop()
        else:
            parts.append(part)
    try:
        resolved = (path.parent / target).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SourceManifestError(
            f"source symlink target cannot be resolved: {link_relative}"
        ) from error
    if not resolved.is_relative_to(root_absolute):
        raise SourceManifestError(
            f"source symlink target escapes root: {link_relative}"
        )
    return target


def _entry_json(entry: ManifestEntryModel) -> dict[str, JSONValue]:
    return {
        "bytes": entry.bytes,
        "kind": entry.kind,
        "mode": entry.mode,
        "path": entry.path,
        "sha256": entry.sha256,
    }


if __name__ == "__main__":
    typer.run(main)
