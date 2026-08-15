from tools.quality.tests.quality_hardening.reporting import scenario_title
from tools.quality.tests.quality_hardening.scenario_catalog import (
    QH_N01,
    QH_N02,
    QH_N03,
    QH_N04,
    QH_N17,
    QH_N18,
)
from tools.quality.tests.quality_hardening.source_scenarios import (
    verify_callable_green_variants,
    verify_callable_red,
    verify_decorator_and_nested_counting,
    verify_pinned_tool_suppression_boundaries,
    verify_source_discovery_boundaries,
    verify_source_line_boundaries,
)
from tools.quality.tests.quality_hardening.support import QualityWorkspace


@scenario_title(QH_N01)
def test_callable_green_variants() -> None:
    verify_callable_green_variants()


@scenario_title(QH_N02)
def test_callable_red() -> None:
    verify_callable_red()


@scenario_title(QH_N03)
def test_decorator_and_nested_counting() -> None:
    verify_decorator_and_nested_counting()


@scenario_title(QH_N04)
def test_source_line_boundaries(quality_workspace: QualityWorkspace) -> None:
    verify_source_line_boundaries(quality_workspace)


@scenario_title(QH_N17)
def test_source_discovery_boundaries(
    quality_workspace: QualityWorkspace,
) -> None:
    verify_source_discovery_boundaries(quality_workspace)


@scenario_title(QH_N18)
def test_pinned_tool_suppression_boundaries(
    quality_workspace: QualityWorkspace,
) -> None:
    verify_pinned_tool_suppression_boundaries(quality_workspace)
