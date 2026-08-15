import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from tools.project_state.model import (
    JSONValue,
    PublicationStatus,
    ValidationResult,
    ValidationStatus,
)
from tools.project_state.publication import publish_state
from tools.project_state.repository import GitTree
from tools.project_state.validation import render_candidate, validate_candidate

ROOT = Path(__file__).resolve().parents[2]
app = typer.Typer(
    add_completion=False, no_args_is_help=True, pretty_exceptions_enable=False
)
Repo = Annotated[Path, typer.Option(help="Coordination repository")]
Tree = Annotated[str, typer.Option(help="Candidate Git tree")]


def _print_json(value: dict[str, JSONValue]) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True))


@app.command()
def check(
    repo: Repo = ROOT,
    tree: Tree = "HEAD",
    max_findings: Annotated[int | None, typer.Option(min=1)] = None,
) -> None:
    candidate = GitTree.resolve(repo.resolve(), tree)
    if candidate is None:
        raise typer.BadParameter("tree must resolve to a Git commit", param_hint="tree")
    result = validate_candidate(candidate, max_findings).result
    _print_json(result.as_dict())
    if result.status is not ValidationStatus.PASS:
        raise typer.Exit(1)


@app.command()
def render(
    repo: Repo = ROOT,
    tree: Tree = "HEAD",
) -> None:
    candidate = GitTree.resolve(repo.resolve(), tree)
    if candidate is None:
        raise typer.BadParameter("tree must resolve to a Git commit", param_hint="tree")
    result = render_candidate(candidate)
    if isinstance(result, ValidationResult):
        _print_json(result.as_dict())
        raise typer.Exit(1)
    sys.stdout.buffer.write(result)


@app.command()
def publish(
    ref: Annotated[str, typer.Option(help="Canonical coordination ref")],
    expected_parent: Annotated[str, typer.Option(help="Expected parent revision")],
    expected_state_sha256: Annotated[str, typer.Option(help="Expected state SHA-256")],
    candidate_state: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    repo: Repo = ROOT,
) -> None:
    result = publish_state(
        repo.resolve(),
        ref,
        expected_parent,
        expected_state_sha256,
        candidate_state.read_bytes(),
    )
    _print_json(result.as_dict())
    if result.result is not PublicationStatus.PASS:
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
