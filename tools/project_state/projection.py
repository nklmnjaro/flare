import posixpath

from tools.project_state.model import CoordinationState


def _link(reference: str) -> str:
    return posixpath.relpath(reference, start="docs/project")


def render_projection(state: CoordinationState) -> bytes:
    lines = [
        (
            "<!-- Bounded human summary generated from docs/project/state.json; "
            "state.json remains the canonical recovery source. -->"
        ),
        "# Flare Current Coordination State",
        "",
        "For complete recovery, read `state.json` and its referenced authorities.",
        "",
        f"- Project: `{state.project_id}`",
        f"- Schema: `{state.schema_version}`",
        f"- Accepted source baseline: `{state.accepted_source_baseline.git_commit}`",
        f"- Product phase: [{state.product_phase_ref}]({_link(state.product_phase_ref)})",
        (
            f"- Production gate: [{state.production_gate_ref}]"
            f"({_link(state.production_gate_ref)})"
        ),
        f"- Integrator: `{state.integrator.assignee_ref}`",
        "",
        "## Active changes",
        "",
    ]
    if state.active_changes:
        lines.extend(
            (
                f"- `{change.change_id}` — [{change.contract_ref}]"
                f"({_link(change.contract_ref)})"
            )
            for change in state.active_changes
        )
    else:
        lines.append("None.")
    lines.extend(["", "## Next actions", ""])
    if state.next_action_change_ids:
        lines.extend(f"- `{change_id}`" for change_id in state.next_action_change_ids)
    else:
        lines.append("None; resolve the referenced blockers or decisions.")
    lines.extend(["", "## Open blockers", ""])
    if state.open_blockers:
        lines.extend(
            f"- `{blocker.blocker_id}` — `{blocker.blocker_ref}`"
            for blocker in state.open_blockers
        )
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines).encode("utf-8")
