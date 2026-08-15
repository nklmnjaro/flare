from tools.quality.tests.quality_hardening.assertions import (
    check_contains,
    check_equal,
    check_not_contains,
    check_process,
)
from tools.quality.tests.quality_hardening.reporting import reported, step
from tools.quality.tests.quality_hardening.repository_policy_support import (
    create_repository_policy_fixture,
)
from tools.quality.tests.quality_hardening.scenario_catalog import (
    QH_N07,
    QH_N08,
    QH_N09,
)
from tools.quality.tests.quality_hardening.support import (
    REPO_ROOT,
    QualityWorkspace,
)

_FORBIDDEN_SECRET_NAMES = (
    ".env",
    ".env.local",
    "credentials.json",
    "credentials.yaml",
    "secrets.txt",
    "private.pem",
    "private.key",
    "id_rsa",
)


def _verify_required_file_symlink_boundaries(
    workspace: QualityWorkspace,
) -> None:
    outside = workspace.root / "outside-gitlint"
    outside.write_text("[general]\nignore = body-is-missing\n", encoding="utf-8")
    for label, with_git in (("git", True), ("no-git", False)):
        fixture = create_repository_policy_fixture(
            workspace.root / f"required-symlink-{label}",
            with_git=with_git,
        )
        fixture.remove(".gitlint")
        (fixture.root / ".gitlint").symlink_to(outside)
        if with_git:
            fixture.require_git("add", "-f", ".gitlint")
        rejected = fixture.policy(pr_title="fix(quality): reject symlink config")
        check_process(rejected, 1, f"проверка required symlink {label}")
        check_contains(
            "invalid required repository file: .gitlint",
            rejected.stdout,
            f"диагностика required symlink {label}",
        )


@reported(QH_N07)
def verify_repository_structure_and_title(workspace: QualityWorkspace) -> None:
    with step("Принять полный repository fixture"):
        good = create_repository_policy_fixture(workspace.root / "good")
        accepted = good.policy(
            pr_title="test(quality): prove repository policy",
        )
        check_process(accepted, 0, "known-good policy")
        check_contains("REPO POLICY: PASS", accepted.stdout, "policy output")
    with step("Отклонить отсутствующий обязательный файл"):
        missing = create_repository_policy_fixture(workspace.root / "missing")
        missing.remove("docs/onboarding/START-HERE.md")
        policy = missing.policy()
        doctor = missing.policy("--doctor")
        diagnostic = "missing required repository file: docs/onboarding/START-HERE.md"
        check_process(policy, 1, "missing-file policy")
        check_contains(diagnostic, policy.stdout, "missing-file policy output")
        check_process(doctor, 1, "missing-file doctor")
        check_contains(diagnostic, doctor.stdout, "missing-file doctor output")
    with step("Отклонить malformed и overlong PR title"):
        malformed = good.policy(pr_title="quality please pass")
        title = "fix(quality): " + "x" * 60
        overlong = good.policy(pr_title=title)
        check_process(malformed, 1, "malformed PR title")
        check_contains(
            "Title does not match regex", malformed.stdout, "malformed title"
        )
        check_process(overlong, 1, "overlong PR title")
        check_contains("Title exceeds max length", overlong.stdout, "overlong title")
    with step("Отклонить required-file symlink в Git и source-only tree"):
        _verify_required_file_symlink_boundaries(workspace)


def _verify_source_only_secret_boundaries(workspace: QualityWorkspace) -> None:
    with step("Отклонить bounded secret-like имена в source-only tree"):
        archive = create_repository_policy_fixture(
            workspace.root / "archive", with_git=False
        )
        for name in _FORBIDDEN_SECRET_NAMES:
            archive.write(name, "NOT_A_REAL_SECRET=1\n")
        rejected = archive.policy()
        check_process(rejected, 1, "проверка source-only secret-like имён")
        for name in _FORBIDDEN_SECRET_NAMES:
            check_contains(
                f"forbidden tracked/source file: {name}",
                rejected.stdout,
                f"диагностика source-only {name}",
            )
    with step("Отклонить nested secret-like имена в source-only tree"):
        nested = create_repository_policy_fixture(
            workspace.root / "nested-archive",
            with_git=False,
        )
        nested_names = (
            "config/.env",
            "certificates/private.pem",
            "settings/credentials.json",
        )
        for name in nested_names:
            nested.write(name, "NOT_A_REAL_SECRET=1\n")
        rejected = nested.policy()
        check_process(rejected, 1, "проверка nested source-only secrets")
        for name in nested_names:
            check_contains(
                f"forbidden tracked/source file: {name}",
                rejected.stdout,
                f"диагностика nested source-only {name}",
            )
    with step("Не расширять secret hygiene на excluded tool trees"):
        excluded = create_repository_policy_fixture(
            workspace.root / "excluded-archive",
            with_git=False,
        )
        for name in (
            "vendor/.env",
            "generated/private.pem",
            ".cache/credentials.json",
            ".venv/lib/python3.14/secrets.py",
        ):
            excluded.write(name, "NOT_A_REAL_SECRET=1\n")
        check_process(excluded.policy(), 0, "проверка excluded source-only trees")
    with step("Отклонить force-tracked secret внутри excluded tree"):
        tracked_nested = create_repository_policy_fixture(
            workspace.root / "tracked-nested"
        )
        tracked_nested.write("vendor/.env", "NOT_A_REAL_SECRET=1\n")
        tracked_nested.require_git("add", "-f", "vendor/.env")
        rejected = tracked_nested.policy()
        check_process(rejected, 1, "проверка tracked nested secret")
        check_contains(
            "forbidden tracked/source file: vendor/.env",
            rejected.stdout,
            "диагностика tracked nested secret",
        )


@reported(QH_N08)
def verify_repository_secret_and_index_boundaries(workspace: QualityWorkspace) -> None:
    with step("Не считать ignored local env частью tracked source"):
        ignored = create_repository_policy_fixture(workspace.root / "ignored")
        ignored.write(".env", "LOCAL_ONLY=1\n")
        ignored.write(".env.local", "LOCAL_ONLY=1\n")
        result = ignored.policy()
        check_process(result, 0, "проверка ignored local env")
    with step("Принять tracked .env.example"):
        tracked = create_repository_policy_fixture(workspace.root / "tracked")
        tracked.write(
            ".env.example",
            "SAFE_PLACEHOLDER=change-me\n",
        )
        tracked.require_git("add", ".env.example")
        accepted = tracked.policy()
        check_process(accepted, 0, "проверка tracked env example")
    with step("Отклонить bounded secret-like имена только после git add"):
        for index, name in enumerate(_FORBIDDEN_SECRET_NAMES, 1):
            fixture = create_repository_policy_fixture(
                workspace.root / f"forbidden-{index}"
            )
            fixture.write(name, "NOT_A_REAL_SECRET=1\n")
            fixture.require_git("add", "-f", name)
            rejected = fixture.policy()
            check_process(rejected, 1, f"проверка tracked {name}")
            check_contains(
                f"forbidden tracked/source file: {name}",
                rejected.stdout,
                f"диагностика {name}",
            )
    _verify_source_only_secret_boundaries(workspace)
    with step("Детерминированно отклонить повреждённый Git index"):
        malformed = create_repository_policy_fixture(workspace.root / "malformed")
        malformed.write_bytes(".git/index", b"not-a-git-index")
        first = malformed.policy()
        second = malformed.policy()
        doctor = malformed.policy("--doctor")
        check_process(first, 1, "malformed index first run")
        check_process(second, 1, "malformed index second run")
        check_equal(first.stdout, second.stdout, "malformed index diagnostics")
        check_contains("unable to read Git index", first.stdout, "index diagnostic")
        check_process(doctor, 1, "malformed index doctor")


@reported(QH_N09)
def verify_repository_doctor_and_facade(workspace: QualityWorkspace) -> None:
    with step("Не изменять source при repository doctor"):
        repository = create_repository_policy_fixture(workspace.root / "doctor")
        before = repository.snapshot()
        result = repository.policy("--doctor")
        after = repository.snapshot()
        check_process(result, 0, "repository doctor")
        check_contains("doctor=PASS", result.stdout, "repository doctor output")
        check_equal(after, before, "repository doctor source snapshot")
    with step("Вызывать canonical Make facade из provider workflow"):
        workflow = (REPO_ROOT / ".github/workflows/repo-policy.yml").read_text(
            encoding="utf-8"
        )
        check_contains(
            'version: "0.12.3"',
            workflow,
            "provider workflow pinned uv",
        )
        check_contains(
            "FLARE_HOST_UV: ${{ steps.setup-uv.outputs.uv-path }}",
            workflow,
            "provider workflow explicit uv",
        )
        check_contains(
            "run: |\n          make bootstrap\n          make check-fast\n",
            workflow,
            "provider workflow canonical sequence",
        )
        check_not_contains(
            "run: python3 tools/quality/check_repo_policy.py",
            workflow,
            "provider workflow",
        )
