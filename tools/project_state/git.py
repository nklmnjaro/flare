import os
import subprocess
from pathlib import Path


def run_git(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["git", "-C", str(repo.resolve()), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
        env=process_env,
    )
