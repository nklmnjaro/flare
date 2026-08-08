#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

CONFIG_PATH = Path(__file__).with_name("config.toml")
PRODUCTION_FREEZE = True


@dataclass(frozen=True, slots=True)
class Role:
    name: str
    display: str
    timing: str
    task: Path
    dependency_profile: str | None


@dataclass(frozen=True, slots=True)
class Config:
    max_bundle_mib: int
    artifact_dir: Path
    governance_dir: Path
    roles: tuple[Role, ...]

    @property
    def dependency_profiles(self) -> tuple[str, ...]:
        return tuple(
            role.dependency_profile
            for role in self.roles
            if role.dependency_profile is not None
        )


@dataclass(frozen=True, slots=True)
class Bundle:
    profile: str
    path: Path
    sha_path: Path
    sha256: str
    size_mib: int


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def output(args: list[str], *, cwd: Path | None = None) -> str:
    return run(args, cwd=cwd, capture=True).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sha(path: Path) -> Path:
    result = Path(f"{path}.sha256")
    result.write_text(f"{sha256(path)}  {path.name}\n", encoding="utf-8")
    return result


def load_config(repo: Path, config_path: Path = CONFIG_PATH) -> Config:
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    dispatch = raw["dispatch"]
    roles: list[Role] = []
    for name, values in raw["roles"].items():
        profile = values.get("dependency_profile")
        roles.append(
            Role(
                name=name,
                display=values["display"],
                timing=values["timing"],
                task=(config_path.parent / values["task"]).resolve(),
                dependency_profile=profile or None,
            )
        )
    config = Config(
        max_bundle_mib=int(dispatch["max_bundle_mib"]),
        artifact_dir=(repo / dispatch["artifact_dir"]).resolve(),
        governance_dir=(repo / dispatch["governance_dir"]).resolve(),
        roles=tuple(roles),
    )
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    expected_roles = {
        "backend",
        "frontend",
        "qa1",
        "qa2",
        "platform",
        "linter",
        "analyst",
        "product_owner",
        "gatekeeper",
    }
    names = {role.name for role in config.roles}
    if names != expected_roles:
        raise ValueError(
            "role set must be exactly "
            f"{sorted(expected_roles)}, got {sorted(names)}"
        )
    profiles = config.dependency_profiles
    expected_profiles = ("backend", "frontend", "qa1", "qa2", "platform", "linter")
    if tuple(profiles) != expected_profiles:
        raise ValueError(
            f"dependency profiles must be {expected_profiles}, got {profiles}"
        )
    displays = [role.display for role in config.roles]
    if len(displays) != len(set(displays)):
        raise ValueError("role display names must be unique")
    for role in config.roles:
        if role.timing not in {"ACT_NOW", "HOLD"}:
            raise ValueError(f"invalid timing for {role.name}: {role.timing}")
        if not role.task.is_file():
            raise ValueError(f"task template missing for {role.name}: {role.task}")


def verify_repo(
    repo: Path,
    *,
    require_clean: bool = True,
) -> tuple[str, str, str]:
    if not (repo / ".git").is_dir():
        raise SystemExit(f"[dispatch][ERROR] git repo missing: {repo}")

    dirty = output(["git", "status", "--porcelain"], cwd=repo)
    if require_clean and dirty:
        print(dirty, file=sys.stderr)
        raise SystemExit("[dispatch][ERROR] repository must be clean")

    head = output(["git", "rev-parse", "HEAD"], cwd=repo)
    branch = output(["git", "branch", "--show-current"], cwd=repo)
    remote = output(["git", "config", "--get", "remote.origin.url"], cwd=repo)

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", ".flare/.dispatch-probe"],
        cwd=repo,
        check=False,
    )
    if ignored.returncode != 0:
        raise SystemExit(
            "[dispatch][ERROR] .flare/ must be canonical ignored local state"
        )
    return head, branch, remote


def build_baseline(
    repo: Path,
    destination: Path,
    *,
    head: str,
    stamp: str,
) -> tuple[Path, Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    short = head[:7]
    name = f"flare-baseline-{stamp}-{short}"
    archive = destination / f"{name}.zip"
    run(
        [
            "git",
            "archive",
            "--format=zip",
            "--prefix=flare/",
            "-o",
            str(archive),
            "HEAD",
        ],
        cwd=repo,
    )
    sha_path = write_sha(archive)
    metadata = destination / f"{name}.metadata.txt"
    metadata.write_text(
        "\n".join(
            [
                f"baseline_id={name}",
                f"commit={head}",
                f"short_commit={short}",
                f"created_utc={stamp}",
                f"archive={archive.name}",
                f"sha256={sha256(archive)}",
                "source_method=git archive HEAD",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return archive, sha_path, metadata


def _newest_bundle(directory: Path, profile: str) -> Path:
    bundles = list(directory.glob(f"flare-dependencies-{profile}-linux-*.tar.gz"))
    if len(bundles) != 1:
        raise SystemExit(
            "[dispatch][ERROR] expected exactly one "
            f"{profile} bundle, got {len(bundles)}"
        )
    return bundles[0]


def verify_detached_sha(artifact: Path, sha_path: Path) -> str:
    line = sha_path.read_text(encoding="utf-8").strip()
    parts = line.split(maxsplit=1)
    if len(parts) != 2:
        raise SystemExit(f"[dispatch][ERROR] malformed SHA file: {sha_path}")
    expected, named = parts
    if Path(named.strip().lstrip("*")).name != artifact.name:
        raise SystemExit(
            f"[dispatch][ERROR] SHA filename mismatch for {artifact.name}: {named}"
        )
    actual = sha256(artifact)
    if actual != expected:
        raise SystemExit(
            f"[dispatch][ERROR] SHA mismatch for {artifact.name}: "
            f"{actual} != {expected}"
        )
    return actual


def build_dependencies(
    repo: Path,
    config: Config,
    *,
    head: str,
    stamp: str,
) -> tuple[Path, dict[str, Bundle]]:
    root = config.artifact_dir / "dependencies"
    root.mkdir(parents=True, exist_ok=True)
    final = root / f"dependency-dist-{stamp}-{head[:7]}"
    staging = root / f".staging-{stamp}-{head[:7]}-{os.getpid()}"
    if final.exists() or staging.exists():
        raise SystemExit(f"[dispatch][ERROR] output already exists: {final}")
    staging.mkdir(parents=True)

    try:
        run(
            ["bash", "tools/platform/dependency_bundles/tests/smoke_fake_toolchain.sh"],
            cwd=repo,
        )
        env = os.environ.copy()
        env["FLARE_ROLE_BUNDLE_MAX_MIB"] = str(config.max_bundle_mib)
        run(
            [
                str(
                    repo
                    / "tools/platform/dependency_bundles/build_all_role_bundles.sh"
                ),
                str(repo),
                str(staging),
            ],
            cwd=repo,
            env=env,
        )

        if list(staging.glob("flare-dependencies-all-linux-*.tar.gz")):
            raise SystemExit("[dispatch][ERROR] umbrella all-profile bundle is forbidden")

        bundles: dict[str, Bundle] = {}
        registry_rows = ["role\tartifact\tsha256\tsize_mib"]
        for profile in config.dependency_profiles:
            artifact = _newest_bundle(staging, profile)
            sha_path = Path(f"{artifact}.sha256")
            if not sha_path.is_file():
                raise SystemExit(
                    f"[dispatch][ERROR] detached SHA missing: {sha_path}"
                )
            digest = verify_detached_sha(artifact, sha_path)
            size = artifact.stat().st_size
            if size > config.max_bundle_mib * 1024 * 1024:
                raise SystemExit(
                    f"[dispatch][ERROR] {profile} bundle exceeds "
                    f"{config.max_bundle_mib} MiB"
                )
            size_mib = (size + 1024 * 1024 - 1) // (1024 * 1024)
            bundles[profile] = Bundle(
                profile=profile,
                path=artifact,
                sha_path=sha_path,
                sha256=digest,
                size_mib=size_mib,
            )
            registry_rows.append(
                f"{profile}\t{artifact.name}\t{digest}\t{size_mib}"
            )

        (staging / "BUNDLE_REGISTRY.tsv").write_text(
            "\n".join(registry_rows) + "\n",
            encoding="utf-8",
        )
        staging.rename(final)
        rebound = {
            profile: Bundle(
                profile=bundle.profile,
                path=final / bundle.path.name,
                sha_path=final / bundle.sha_path.name,
                sha256=bundle.sha256,
                size_mib=bundle.size_mib,
            )
            for profile, bundle in bundles.items()
        }
        return final, rebound
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _zip_add(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    stored = source.name.endswith((".zip", ".tar.gz", ".tgz", ".gz"))
    zf.write(
        source,
        arcname=arcname,
        compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
    )


def _render_task(role: Role, variables: dict[str, str], destination: Path) -> None:
    template = Template(role.task.read_text(encoding="utf-8"))
    destination.write_text(
        template.substitute(variables),
        encoding="utf-8",
    )


def packet_filename(role: Role, short: str) -> str:
    prefix = "SEND_NOW" if role.timing == "ACT_NOW" else "HOLD"
    return f"{prefix}__flare-handoff-{role.display}-{short}.zip"


def _write_checksums(directory: Path) -> Path:
    rows = [
        f"{sha256(path)}  {path.name}"
        for path in sorted(directory.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    result = directory / "SHA256SUMS"
    result.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return result


def _copy_governance(config: Config, destination: Path) -> None:
    if not config.governance_dir.is_dir():
        raise SystemExit(
            f"[dispatch][ERROR] governance directory missing: "
            f"{config.governance_dir}"
        )
    target = destination / "governance"
    target.mkdir()
    files = sorted(
        path for path in config.governance_dir.iterdir() if path.is_file()
    )
    if not files:
        raise SystemExit("[dispatch][ERROR] governance directory is empty")
    for source in files:
        shutil.copy2(source, target / source.name)


def make_packet(
    *,
    role: Role,
    destination: Path,
    baseline: tuple[Path, Path, Path],
    registry: Path,
    bundles: dict[str, Bundle],
    config: Config,
    source_manifest: Path,
    variables: dict[str, str],
) -> tuple[Path, Path]:
    packet_dir = destination / f".packet-{role.display}"
    packet_dir.mkdir()
    try:
        _render_task(role, variables, packet_dir / "TASK.md")
        for baseline_part in baseline:
            shutil.copy2(baseline_part, packet_dir / baseline_part.name)
        shutil.copy2(source_manifest, packet_dir / "SOURCE_MANIFEST.json")
        shutil.copy2(registry, packet_dir / "BUNDLE_REGISTRY.tsv")
        _copy_governance(config, packet_dir)

        if role.dependency_profile is not None:
            bundle = bundles[role.dependency_profile]
            shutil.copy2(bundle.path, packet_dir / bundle.path.name)
            shutil.copy2(bundle.sha_path, packet_dir / bundle.sha_path.name)

        (packet_dir / "README_FIRST.md").write_text(
            "\n".join(
                [
                    f"# {role.display} — Flare worker packet",
                    "",
                    f"Timing: `{role.timing}`",
                    f"Source commit: `{variables['source_commit']}`",
                    f"Baseline SHA-256: `{variables['baseline_sha256']}`",
                    "Dependency profile: "
                    f"`{role.dependency_profile or 'none'}`",
                    "",
                    "1. Verify `SHA256SUMS`.",
                    "2. Read `TASK.md` before source changes.",
                    "3. Run TASK PREFLIGHT and challenge stale premises.",
                    "4. Production freeze remains active until explicit "
                    "`APPROVE FLARE-000`.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        _write_checksums(packet_dir)

        archive = destination / packet_filename(
            role, variables["source_commit"][:7]
        )
        with zipfile.ZipFile(archive, "w") as zf:
            prefix = f"{role.display}-{variables['source_commit'][:7]}"
            for path in sorted(packet_dir.rglob("*")):
                if path.is_file():
                    _zip_add(
                        zf,
                        path,
                        f"{prefix}/{path.relative_to(packet_dir)}",
                    )
        sha_path = write_sha(archive)
        return archive, sha_path
    finally:
        shutil.rmtree(packet_dir, ignore_errors=True)


def build_dispatch(
    repo: Path,
    config: Config,
    *,
    head: str,
    branch: str,
    remote: str,
    stamp: str,
    dependency_dir: Path,
    bundles: dict[str, Bundle],
) -> Path:
    baseline_root = config.artifact_dir / "baselines"
    dispatch_root = config.artifact_dir / "team-dispatch"
    baseline = build_baseline(
        repo,
        baseline_root,
        head=head,
        stamp=stamp,
    )

    final = dispatch_root / f"wave-{stamp}-{head[:7]}"
    staging = dispatch_root / f".staging-{stamp}-{head[:7]}-{os.getpid()}"
    dispatch_root.mkdir(parents=True, exist_ok=True)
    if final.exists() or staging.exists():
        raise SystemExit(f"[dispatch][ERROR] dispatch output exists: {final}")
    staging.mkdir(parents=True)

    try:
        source_manifest = staging / "SOURCE_MANIFEST.json"
        manifest = {
            "source": {
                "commit": head,
                "branch": branch,
                "remote_origin": remote,
            },
            "created_utc": stamp,
            "baseline": {
                "file": baseline[0].name,
                "sha256": sha256(baseline[0]),
            },
            "dependency_distribution": str(dependency_dir),
            "bundles": {
                profile: {
                    "file": bundle.path.name,
                    "sha256": bundle.sha256,
                    "size_mib": bundle.size_mib,
                }
                for profile, bundle in bundles.items()
            },
            "production_freeze": PRODUCTION_FREEZE,
            "approve_flare_000": False,
        }
        source_manifest.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        variables = {
            "source_commit": head,
            "baseline_sha256": sha256(baseline[0]),
            "production_freeze": "ACTIVE",
        }

        rows = [
            "role\tdisplay\ttiming\tpacket\tpacket_sha256\t"
            "dependency_profile\tbundle_sha256"
        ]
        for role in config.roles:
            packet, _ = make_packet(
                role=role,
                destination=staging,
                baseline=baseline,
                registry=dependency_dir / "BUNDLE_REGISTRY.tsv",
                bundles=bundles,
                config=config,
                source_manifest=source_manifest,
                variables=variables,
            )
            bundle_sha = (
                bundles[role.dependency_profile].sha256
                if role.dependency_profile is not None
                else "-"
            )
            rows.append(
                f"{role.name}\t{role.display}\t{role.timing}\t"
                f"{packet.name}\t{sha256(packet)}\t"
                f"{role.dependency_profile or '-'}\t{bundle_sha}"
            )
        (staging / "WHO_GETS_WHAT.tsv").write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )

        human = [
            "# Что кому пересылать",
            "",
            f"Source commit: `{head}`",
            f"Baseline SHA-256: `{variables['baseline_sha256']}`",
            "",
            "## Переслать сейчас",
            "",
        ]
        for role in config.roles:
            if role.timing == "ACT_NOW":
                human.append(
                    f"- {role.display} → "
                    f"`{packet_filename(role, head[:7])}`"
                )
        human.extend(["", "## HOLD", ""])
        for role in config.roles:
            if role.timing == "HOLD":
                human.append(
                    f"- {role.display} → "
                    f"`{packet_filename(role, head[:7])}`"
                )
        human.extend(
            [
                "",
                "Каждый ZIP самодостаточен: baseline, task, governance, "
                "manifest и только нужный dependency profile.",
                "",
            ]
        )
        (staging / "WHO_GETS_WHAT.md").write_text(
            "\n".join(human),
            encoding="utf-8",
        )
        _write_checksums(staging)
        staging.rename(final)
        return final
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _read_registry(
    directory: Path,
    config: Config,
) -> dict[str, Bundle]:
    registry = directory / "BUNDLE_REGISTRY.tsv"
    if not registry.is_file():
        raise SystemExit(f"[dispatch][ERROR] registry missing: {registry}")
    rows = registry.read_text(encoding="utf-8").splitlines()
    if not rows or rows[0] != "role\tartifact\tsha256\tsize_mib":
        raise SystemExit("[dispatch][ERROR] malformed bundle registry header")

    bundles: dict[str, Bundle] = {}
    for row in rows[1:]:
        profile, artifact_name, digest, size_text = row.split("\t")
        artifact = directory / artifact_name
        sha_path = Path(f"{artifact}.sha256")
        if profile not in config.dependency_profiles:
            raise SystemExit(
                f"[dispatch][ERROR] unexpected dependency profile: {profile}"
            )
        actual = verify_detached_sha(artifact, sha_path)
        if actual != digest:
            raise SystemExit(
                f"[dispatch][ERROR] registry SHA mismatch for {profile}"
            )
        size_mib = int(size_text)
        if size_mib > config.max_bundle_mib:
            raise SystemExit(
                f"[dispatch][ERROR] registry size exceeds budget: {profile}"
            )
        bundles[profile] = Bundle(
            profile=profile,
            path=artifact,
            sha_path=sha_path,
            sha256=digest,
            size_mib=size_mib,
        )

    if tuple(bundles) != config.dependency_profiles:
        raise SystemExit(
            "[dispatch][ERROR] dependency registry profile set/order mismatch"
        )
    return bundles


def _replace_symlink(link: Path, target: Path) -> None:
    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            raise SystemExit(
                f"[dispatch][ERROR] refusing to replace real directory: {link}"
            )
        link.unlink()
    link.symlink_to(os.path.relpath(target, link.parent))


def verify_dispatch(path: Path) -> None:
    required = {
        "SOURCE_MANIFEST.json",
        "WHO_GETS_WHAT.md",
        "WHO_GETS_WHAT.tsv",
        "SHA256SUMS",
    }
    names = {item.name for item in path.iterdir() if item.is_file()}
    missing = required - names
    if missing:
        raise SystemExit(
            f"[dispatch][ERROR] dispatch missing required files: "
            f"{sorted(missing)}"
        )

    expected_checksums: dict[str, str] = {}
    for line in (path / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        expected_checksums[name.strip()] = digest

    for name, digest in expected_checksums.items():
        artifact = path / name
        if not artifact.is_file():
            raise SystemExit(
                f"[dispatch][ERROR] checksummed artifact missing: {name}"
            )
        if sha256(artifact) != digest:
            raise SystemExit(
                f"[dispatch][ERROR] dispatch SHA mismatch: {name}"
            )

    packet_zips = sorted(path.glob("*__flare-handoff-*.zip"))
    if len(packet_zips) != 9:
        raise SystemExit(
            f"[dispatch][ERROR] expected 9 role packets, got {len(packet_zips)}"
        )
    for archive in packet_zips:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                part = Path(info.filename)
                if part.is_absolute() or ".." in part.parts:
                    raise SystemExit(
                        f"[dispatch][ERROR] unsafe ZIP path in {archive.name}: "
                        f"{info.filename}"
                    )
            bad = zf.testzip()
            if bad is not None:
                raise SystemExit(
                    f"[dispatch][ERROR] corrupt ZIP member in "
                    f"{archive.name}: {bad}"
                )


def _current_dependency_dir(config: Config) -> Path:
    current = config.artifact_dir / "dependencies" / "current"
    if not current.is_symlink():
        raise SystemExit(
            "[dispatch][ERROR] dependency current symlink missing; "
            "run deps-build first"
        )
    return current.resolve()


def command_doctor(repo: Path, config: Config) -> int:
    head, branch, remote = verify_repo(repo, require_clean=False)
    required = [
        repo / "tools/platform/dependency_bundles/build_all_role_bundles.sh",
        repo / "tools/platform/dependency_bundles/tests/smoke_fake_toolchain.sh",
        config.governance_dir,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "[dispatch][ERROR] required repository inputs missing: "
            + ", ".join(missing)
        )
    print("TEAM DISPATCH DOCTOR PASS")
    print(f"source_commit={head}")
    print(f"branch={branch}")
    print(f"remote_origin={remote}")
    print(f"artifact_dir={config.artifact_dir}")
    return 0


def command_deps(repo: Path, config: Config) -> int:
    head, _, _ = verify_repo(repo)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory, _ = build_dependencies(
        repo,
        config,
        head=head,
        stamp=stamp,
    )
    current = config.artifact_dir / "dependencies" / "current"
    _replace_symlink(current, directory)
    print(f"DEPENDENCIES={directory}")
    return 0


def command_dispatch(repo: Path, config: Config) -> int:
    head, branch, remote = verify_repo(repo)
    dependency_dir = _current_dependency_dir(config)
    bundles = _read_registry(dependency_dir, config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = build_dispatch(
        repo,
        config,
        head=head,
        branch=branch,
        remote=remote,
        stamp=stamp,
        dependency_dir=dependency_dir,
        bundles=bundles,
    )
    _replace_symlink(config.artifact_dir / "team-dispatch" / "current", final)
    print(f"TEAM_PACKETS={final}")
    print(f"FORWARD_MAP={final / 'WHO_GETS_WHAT.md'}")
    return 0


def command_verify(repo: Path, config: Config) -> int:
    verify_repo(repo)
    dependency_dir = _current_dependency_dir(config)
    _read_registry(dependency_dir, config)
    current = config.artifact_dir / "team-dispatch" / "current"
    if not current.is_symlink():
        raise SystemExit("[dispatch][ERROR] team-dispatch/current missing")
    verify_dispatch(current.resolve())
    print("TEAM DISPATCH VERIFY PASS")
    return 0


def command_all(repo: Path, config: Config) -> int:
    command_doctor(repo, config)
    command_deps(repo, config)
    command_dispatch(repo, config)
    command_verify(repo, config)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build reproducible Flare role dependency and task packets."
    )
    parser.add_argument(
        "command",
        choices=("doctor", "deps", "dispatch", "verify", "all"),
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Flare Git repository root (default: current directory)",
    )
    args = parser.parse_args()

    repo = args.repo.resolve()
    config = load_config(repo)
    handlers = {
        "doctor": command_doctor,
        "deps": command_deps,
        "dispatch": command_dispatch,
        "verify": command_verify,
        "all": command_all,
    }
    return handlers[args.command](repo, config)


if __name__ == "__main__":
    raise SystemExit(main())
