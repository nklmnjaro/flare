import shutil
import sys
from pathlib import Path

from tools.local_execution.bootstrap import bootstrap_command
from tools.local_execution.commands import dispatch
from tools.local_execution.environment import observe_environment
from tools.local_execution.model import PUBLIC_CAPABILITIES, Capability
from tools.local_execution.process import CommandContext
from tools.local_execution.profile import ProfileError, load_profile

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "tools/local_execution/host_profile.toml"


def _usage() -> str:
    names = "\n".join(f"  {capability.value}" for capability in PUBLIC_CAPABILITIES)
    return f"usage: ./flare <capability>\n\ncapabilities:\n{names}\n"


def _option(arguments: list[str], name: str) -> tuple[str | None, list[str]]:
    remaining: list[str] = []
    found: str | None = None
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if found is not None or index + 1 >= len(arguments):
                raise ValueError(f"option {name} requires one value")
            found = arguments[index + 1]
            index += 2
        else:
            remaining.append(arguments[index])
            index += 1
    return found, remaining


def main(arguments: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if not args or args[0] in {"help", "--help", "-h"}:
        print(_usage(), end="")
        return 0
    name = args.pop(0)
    try:
        capability = Capability(name)
    except ValueError:
        print(f"unknown capability: {name}", file=sys.stderr)
        print(_usage(), file=sys.stderr, end="")
        return 2
    try:
        uv_value, args = _option(args, "--uv")
        managed_value, args = _option(args, "--managed-python")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args:
        print(f"unexpected arguments: {' '.join(args)}", file=sys.stderr)
        return 2
    try:
        profile = load_profile(PROFILE_PATH)
    except ProfileError as error:
        print(f"host profile invalid: {error}", file=sys.stderr)
        return 1
    uv_path = Path(uv_value) if uv_value is not None else None
    if uv_path is None:
        discovered = shutil.which("uv")
        if discovered is None:
            print("required host uv is missing", file=sys.stderr)
            return 1
        uv_path = Path(discovered)
    if capability is Capability.BOOTSTRAP:
        if managed_value is None:
            print("bootstrap requires Stage-0 managed Python identity", file=sys.stderr)
            return 2
        return bootstrap_command(ROOT, profile, uv_path, Path(managed_value))
    if capability is Capability.ENVIRONMENT_MANIFEST:
        environment = profile.path(ROOT, profile.project_environment)
        manifest = observe_environment(ROOT, profile, environment, uv_path)
        sys.stdout.buffer.write(manifest.encoded())
        return 0
    return dispatch(capability, CommandContext(ROOT, profile, uv_path))


if __name__ == "__main__":
    raise SystemExit(main())
