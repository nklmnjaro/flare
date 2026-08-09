from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from tools.local_execution.bootstrap import bootstrap_environment
from tools.local_execution.environment import MANIFEST_NAME, EnvironmentError
from tools.local_execution.model import CheckStatus
from tools.local_execution.profile import ProfileError
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_false,
    assert_not_contains,
    assert_raises,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import (
    attach_text,
    scenario,
    step_context,
)
from tools.quality.tests.local_execution.support import (
    LocalExecutionFixture,
    create_fixture,
    source_snapshot,
    write_fake_uv,
)


@scenario("LF-N01", "Bootstrap cleanly and reuse the exact environment")
def verify_bootstrap_and_repeat(repository: LocalExecutionFixture) -> None:
    before = source_snapshot(repository.root)
    with step_context("Build and atomically activate a validated candidate"):
        first = bootstrap_environment(
            repository.root,
            repository.profile,
            repository.uv,
            repository.managed_python,
        )
        attach_text(
            "bootstrap result",
            f"action={first.action}\nmanifest={first.manifest_sha256}\n",
        )
    after_first = source_snapshot(repository.root)
    with step_context("Repeat bootstrap without replacing correct state"):
        second = bootstrap_environment(
            repository.root,
            repository.profile,
            repository.uv,
            repository.managed_python,
        )
    after_second = source_snapshot(repository.root)
    assert_equal(first.status, CheckStatus.PASS, "first bootstrap status")
    assert_equal(first.action, "CREATED", "first bootstrap action")
    assert_equal(second.status, CheckStatus.PASS, "repeat bootstrap status")
    assert_equal(second.action, "REUSED", "repeat bootstrap action")
    assert_equal(second.manifest_sha256, first.manifest_sha256, "repeat manifest")
    assert_equal(after_first, before, "source after first bootstrap")
    assert_equal(after_second, before, "source after repeat bootstrap")


@scenario("LF-N02", "Recover after interruption before activation")
def verify_interruption_and_recovery(repository: LocalExecutionFixture) -> None:
    class InjectedInterruption(RuntimeError):
        pass

    def interrupt(phase: str) -> None:
        if phase == "before-activation":
            raise InjectedInterruption("intentional interruption")

    def interrupted() -> None:
        bootstrap_environment(
            repository.root,
            repository.profile,
            repository.uv,
            repository.managed_python,
            interrupt,
        )

    assert_raises(InjectedInterruption, interrupted, "fault-injected bootstrap")
    environment = repository.root / repository.profile.project_environment
    assert_false(environment.exists(), "partial candidate is not current")
    candidates = repository.root / repository.profile.project_state / "candidates"
    assert_true(any(candidates.iterdir()), "partial candidate remains isolated")
    recovered = bootstrap_environment(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    )
    assert_equal(recovered.status, CheckStatus.PASS, "recovery status")
    assert_equal(recovered.action, "CREATED", "recovery action")
    assert_true((environment / MANIFEST_NAME).is_file(), "activated manifest")


@scenario("LF-N03", "Reject corrupt state and stale success markers")
def verify_corruption_recovery(repository: LocalExecutionFixture) -> None:
    first = bootstrap_environment(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    )
    environment = repository.root / repository.profile.project_environment
    (environment / MANIFEST_NAME).write_text("corrupt\n", encoding="utf-8")
    (repository.root / repository.profile.uv_cache).mkdir(parents=True, exist_ok=True)
    (repository.root / repository.profile.uv_cache / "poison").write_bytes(b"bad")
    recovered = bootstrap_environment(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    )
    rejected = repository.root / repository.profile.project_state / "rejected"
    assert_equal(first.status, CheckStatus.PASS, "initial bootstrap")
    assert_equal(recovered.status, CheckStatus.PASS, "corrupt-state recovery")
    assert_equal(recovered.action, "CREATED", "corrupt environment replacement")
    assert_true(any(rejected.iterdir()), "rejected environment retained recoverably")
    assert_equal(
        (environment / MANIFEST_NAME).read_bytes().strip().startswith(b"{"),
        True,
        "replacement manifest shape",
    )


@scenario("LF-N04", "Reject wrong or unusable uv")
def verify_uv_integrity_boundaries(repository: LocalExecutionFixture) -> None:
    wrong_version = write_fake_uv(repository.root, version="9.9.9")
    wrong = bootstrap_environment(
        repository.root,
        repository.profile,
        wrong_version,
        repository.managed_python,
    )
    unusable = write_fake_uv(
        repository.root,
        sync_exit=71,
        sync_error="token=local-first-secret-canary",
    )
    failed = bootstrap_environment(
        repository.root,
        repository.profile,
        unusable,
        repository.managed_python,
    )
    valid_uv = write_fake_uv(repository.root)
    recovered = bootstrap_environment(
        repository.root,
        repository.profile,
        valid_uv,
        repository.managed_python,
    )
    assert_equal(wrong.status, CheckStatus.FAIL, "wrong uv version")
    assert_equal(wrong.action, "VALIDATION_FAILED", "wrong uv classification")
    assert_contains("uv version mismatch", wrong.detail, "wrong uv detail")
    assert_equal(failed.status, CheckStatus.FAIL, "unusable uv status")
    assert_equal(failed.action, "SYNC_FAILED", "unusable uv classification")
    assert_not_contains(
        "local-first-secret-canary", failed.detail, "bootstrap failure diagnostic"
    )
    assert_equal(recovered.status, CheckStatus.PASS, "valid retry status")
    assert_equal(recovered.action, "CREATED", "valid retry activation")


@scenario("LF-N05", "Produce equal manifests in twin checkouts")
def verify_twin_checkout_manifests(tmp_path: Path) -> None:
    first_repo = create_fixture(tmp_path / "checkout-a")
    second_repo = create_fixture(tmp_path / "checkout-b")
    first = bootstrap_environment(
        first_repo.root,
        first_repo.profile,
        first_repo.uv,
        first_repo.managed_python,
    )
    second = bootstrap_environment(
        second_repo.root,
        second_repo.profile,
        second_repo.uv,
        second_repo.managed_python,
    )
    assert_equal(first.status, CheckStatus.PASS, "checkout A")
    assert_equal(second.status, CheckStatus.PASS, "checkout B")
    assert_equal(second.manifest_sha256, first.manifest_sha256, "twin manifest")


@scenario("LF-N06", "Serialize concurrent bootstrap")
def verify_concurrent_bootstrap(repository: LocalExecutionFixture) -> None:
    def run() -> tuple[str, str | None]:
        result = bootstrap_environment(
            repository.root,
            repository.profile,
            repository.uv,
            repository.managed_python,
        )
        return result.action, result.manifest_sha256

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: run(), range(2)))
    actions = sorted(action for action, _ in results)
    manifests = {manifest for _, manifest in results}
    assert_equal(actions, ["CREATED", "REUSED"], "concurrent actions")
    assert_equal(len(manifests), 1, "concurrent canonical manifest count")


@scenario("LF-N07", "Reject unsafe bootstrap target paths")
def verify_bootstrap_path_safety(repository: LocalExecutionFixture) -> None:
    unsafe = replace(repository.profile, project_environment="/")

    def run() -> None:
        bootstrap_environment(
            repository.root,
            unsafe,
            repository.uv,
            repository.managed_python,
        )

    assert_raises(ProfileError, run, "root-target bootstrap")

    def run_warm_python() -> None:
        bootstrap_environment(
            repository.root,
            repository.profile,
            repository.uv,
            repository.uv,
        )

    warm_error = assert_raises(
        EnvironmentError, run_warm_python, "host Python outside managed root"
    )
    assert_contains("managed Python", str(warm_error), "managed Python diagnostic")

    external = repository.root.parent / "external-environment"
    external.mkdir()
    environment = repository.root / repository.profile.project_environment
    environment.symlink_to(external, target_is_directory=True)

    def run_symlink() -> None:
        bootstrap_environment(
            repository.root,
            repository.profile,
            repository.uv,
            repository.managed_python,
        )

    error = assert_raises(EnvironmentError, run_symlink, "symlink escape bootstrap")
    assert_contains("escapes", str(error), "symlink escape diagnostic")
    environment.unlink()
    rejected = repository.root / repository.profile.project_state / "rejected"
    rejected.parent.mkdir(parents=True, exist_ok=True)
    rejected.symlink_to(external, target_is_directory=True)
    rejected_error = assert_raises(
        EnvironmentError, run_symlink, "rejected-state symlink escape"
    )
    assert_contains("escapes", str(rejected_error), "rejected symlink diagnostic")
