from pathlib import Path

import allure

from tools.quality.tests.local_execution.bootstrap_scenarios import (
    verify_bootstrap_and_repeat,
    verify_bootstrap_path_safety,
    verify_concurrent_bootstrap,
    verify_corruption_recovery,
    verify_interruption_and_recovery,
    verify_twin_checkout_manifests,
    verify_uv_integrity_boundaries,
)
from tools.quality.tests.local_execution.support import LocalExecutionFixture


@allure.parent_suite("Flare engineering contracts")
@allure.suite("Local-First execution")
@allure.feature("Bootstrap")
class TestBootstrapContract:
    @allure.title("[LF-N01] Bootstrap cleanly and reuse the exact environment")
    def test_bootstrap_repeat(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_bootstrap_and_repeat(local_execution_repository)

    @allure.title("[LF-N02] Recover after interruption before activation")
    def test_interruption_recovery(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_interruption_and_recovery(local_execution_repository)

    @allure.title("[LF-N03] Reject corrupt state and stale success markers")
    def test_corruption_recovery(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_corruption_recovery(local_execution_repository)

    @allure.title("[LF-N04] Reject wrong or unusable uv")
    def test_uv_boundaries(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_uv_integrity_boundaries(local_execution_repository)

    @allure.title("[LF-N05] Produce equal manifests in twin checkouts")
    def test_twin_manifests(self, tmp_path: Path) -> None:
        verify_twin_checkout_manifests(tmp_path)

    @allure.title("[LF-N06] Serialize concurrent bootstrap")
    def test_concurrent_bootstrap(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_concurrent_bootstrap(local_execution_repository)

    @allure.title("[LF-N07] Reject unsafe bootstrap target paths")
    def test_path_safety(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_bootstrap_path_safety(local_execution_repository)
