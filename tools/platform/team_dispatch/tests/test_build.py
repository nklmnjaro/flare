from __future__ import annotations

from pathlib import Path
import hashlib
import tempfile
import unittest

from tools.platform.team_dispatch.build import (
    CONFIG_PATH,
    Role,
    load_config,
    packet_filename,
    sha256,
    verify_detached_sha,
)


class TeamDispatchUnitTests(unittest.TestCase):
    def test_config_has_exact_team_and_profiles(self) -> None:
        repo = CONFIG_PATH.parents[3]
        config = load_config(repo)
        self.assertEqual(
            tuple(role.name for role in config.roles),
            (
                "backend",
                "frontend",
                "qa1",
                "qa2",
                "platform",
                "linter",
                "analyst",
                "product_owner",
                "gatekeeper",
            ),
        )
        self.assertEqual(
            config.dependency_profiles,
            ("backend", "frontend", "qa1", "qa2", "platform", "linter"),
        )

    def test_packet_filename_encodes_timing(self) -> None:
        now = Role("backend", "kolyan_backend", "ACT_NOW", Path("x"), "backend")
        hold = Role("gatekeeper", "kolyan_gatekeeper", "HOLD", Path("x"), None)
        self.assertEqual(
            packet_filename(now, "abcdef0"),
            "SEND_NOW__flare-handoff-kolyan_backend-abcdef0.zip",
        )
        self.assertEqual(
            packet_filename(hold, "abcdef0"),
            "HOLD__flare-handoff-kolyan_gatekeeper-abcdef0.zip",
        )

    def test_detached_sha_rejects_wrong_digest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "x.tar.gz"
            artifact.write_bytes(b"payload")
            sha_path = Path(f"{artifact}.sha256")
            sha_path.write_text(f"{'0' * 64}  {artifact.name}\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                verify_detached_sha(artifact, sha_path)

    def test_detached_sha_accepts_exact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "x.tar.gz"
            artifact.write_bytes(b"payload")
            digest = hashlib.sha256(b"payload").hexdigest()
            sha_path = Path(f"{artifact}.sha256")
            sha_path.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
            self.assertEqual(verify_detached_sha(artifact, sha_path), digest)
            self.assertEqual(sha256(artifact), digest)


if __name__ == "__main__":
    unittest.main()
