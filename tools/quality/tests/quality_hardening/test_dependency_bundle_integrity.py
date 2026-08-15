from tools.quality.tests.quality_hardening.bundle_integrity_scenarios import (
    verify_archive_topology_rejections,
    verify_detached_checksum_rejections,
    verify_internal_manifest_rejections,
    verify_valid_dependency_bundles,
)
from tools.quality.tests.quality_hardening.reporting import scenario_title
from tools.quality.tests.quality_hardening.scenario_catalog import (
    QH_N13,
    QH_N14,
    QH_N15,
    QH_N16,
)
from tools.quality.tests.quality_hardening.support import QualityWorkspace


@scenario_title(QH_N13)
def test_valid_dependency_bundles(quality_workspace: QualityWorkspace) -> None:
    verify_valid_dependency_bundles(quality_workspace)


@scenario_title(QH_N14)
def test_internal_manifest_rejections(
    quality_workspace: QualityWorkspace,
) -> None:
    verify_internal_manifest_rejections(quality_workspace)


@scenario_title(QH_N15)
def test_archive_topology_rejections(
    quality_workspace: QualityWorkspace,
) -> None:
    verify_archive_topology_rejections(quality_workspace)


@scenario_title(QH_N16)
def test_detached_checksum_rejections(
    quality_workspace: QualityWorkspace,
) -> None:
    verify_detached_checksum_rejections(quality_workspace)
