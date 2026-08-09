from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.model import PUBLIC_CAPABILITIES

MAKE_POLICY_TOKENS = (
    "ruff ",
    "mypy ",
    "pytest ",
    "--alluredir",
    "tools/quality/check_repo_policy.py",
    "uv sync",
)
STAGE0_POLICY_TOKENS = ("ruff", "mypy", "pytest", "--alluredir", "state-test")


@dataclass(frozen=True, slots=True)
class ArchitectureFinding:
    code: str
    detail: str


def audit_execution_ownership(
    makefile: str,
    stage0: str,
) -> tuple[ArchitectureFinding, ...]:
    findings: list[ArchitectureFinding] = []
    recipe_lines = tuple(
        line.strip() for line in makefile.splitlines() if line.startswith("\t")
    )
    for token in MAKE_POLICY_TOKENS:
        if any(token in line for line in recipe_lines):
            findings.append(
                ArchitectureFinding(
                    "MAKEFILE_POLICY_DUPLICATION",
                    f"Makefile recipe owns canonical token {token!r}",
                )
            )
    for capability in PUBLIC_CAPABILITIES:
        target = capability.value
        expected = f"@./flare {target}"
        if expected not in recipe_lines:
            findings.append(
                ArchitectureFinding(
                    "MISSING_THIN_ADAPTER",
                    f"Makefile target {target!r} must delegate as {expected!r}",
                )
            )
    for token in STAGE0_POLICY_TOKENS:
        if token in stage0:
            findings.append(
                ArchitectureFinding(
                    "STAGE0_POLICY_DUPLICATION",
                    f"Stage-0 owns forbidden quality-policy token {token!r}",
                )
            )
    return tuple(findings)


def architecture_command(root: Path) -> int:
    findings = audit_execution_ownership(
        (root / "Makefile").read_text(encoding="utf-8"),
        (root / "flare").read_text(encoding="utf-8"),
    )
    if findings:
        print("execution-architecture=FAIL")
        for finding in findings:
            print(f"- {finding.code}: {finding.detail}")
        return 1
    print("execution-architecture=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(architecture_command(Path.cwd()))
