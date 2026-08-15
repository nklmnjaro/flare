import json
import os
import sys
from pathlib import Path

from tools.local_execution.process import ProcessSpec, run_process
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_false,
    assert_raises,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import scenario, step_context

NOISY_PROGRAM = """\
import os
import sys
from pathlib import Path

os.write(1, b"x" * 600_000)
os.write(2, b"y" * 600_000)
Path(sys.argv[1]).touch()
"""
DETACHED_PROGRAM = """\
import json
import os
import subprocess
import sys
import time
from pathlib import Path

evidence = Path(sys.argv[1])
child = subprocess.Popen(
    ("/usr/bin/sleep", "300"),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
deadline = time.monotonic() + 5
while os.getpgid(child.pid) != child.pid:
    if time.monotonic() >= deadline:
        raise RuntimeError("detached process group was not established")
    time.sleep(0.01)
evidence.write_text(
    json.dumps(
        {
            "command_pgid": os.getpgrp(),
            "descendant_pgid": os.getpgid(child.pid),
            "pid": child.pid,
        }
    ),
    encoding="ascii",
)
if sys.argv[2] == "wait":
    time.sleep(300)
"""
ISOLATION_PROGRAM = """\
import json
import os
import sys

print(json.dumps({
    "bytecode_environment": os.environ.get("PYTHONDONTWRITEBYTECODE"),
    "dont_write_bytecode": sys.dont_write_bytecode,
    "no_user_site": os.environ.get("PYTHONNOUSERSITE"),
}))
"""


def _signal_zero(identifier: int) -> None:
    os.kill(identifier, 0)


def _detached_evidence(path: Path) -> tuple[int, int, int]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise TypeError("detached evidence is not an object")
    pid = payload.get("pid")
    command_group = payload.get("command_pgid")
    descendant_group = payload.get("descendant_pgid")
    if not isinstance(pid, int):
        raise TypeError("detached evidence PID is invalid")
    if not isinstance(command_group, int) or not isinstance(descendant_group, int):
        raise TypeError("detached evidence process groups are invalid")
    return pid, command_group, descendant_group


def _assert_detached_absent(path: Path, label: str) -> None:
    identifier, command_group, descendant_group = _detached_evidence(path)
    assert_false(
        command_group == descendant_group,
        f"{label}: descendant escaped the command process group",
    )
    assert_raises(
        ProcessLookupError,
        lambda: _signal_zero(identifier),
        f"{label}: detached descendant absent",
    )


@scenario(
    "LF-N40",
    "Ограничивать общий вывод canonical process runner",
    feature="Владение командами",
)
def verify_process_output_limit(tmp_path: Path) -> None:
    with step_context("Подготовить command с общим выводом выше одного мегабайта"):
        completion = tmp_path / "noisy-completed"
        specification = ProcessSpec(
            "noisy-process",
            (sys.executable, "-I", "-B", "-c", NOISY_PROGRAM, str(completion)),
            timeout_seconds=10,
        )
    with step_context("Выполнить command через canonical public runner"):
        result = run_process(specification, tmp_path)
    with step_context("Проверить ранний RED и ограниченные диагностики"):
        assert_equal(result.returncode, 125, "output limit return code")
        assert_contains("combined 1000000-byte output bound", result.stderr, "stderr")
        assert_true(len(result.stdout.encode("utf-8")) < 13_000, "bounded stdout")
        assert_true(len(result.stderr.encode("utf-8")) < 13_000, "bounded stderr")
        assert_false(completion.exists(), "command stopped before completion")


@scenario(
    "LF-N41",
    "Завершать detached дерево по explicit process timeout",
    feature="Владение командами",
)
def verify_process_timeout_tree_cleanup(tmp_path: Path) -> None:
    with step_context("Подготовить command с detached setsid потомком"):
        evidence = tmp_path / "timeout-descendant.json"
        specification = ProcessSpec(
            "timeout-tree",
            (sys.executable, "-I", "-B", "-c", DETACHED_PROGRAM, str(evidence), "wait"),
            timeout_seconds=1,
        )
    with step_context("Дождаться explicit timeout через canonical runner"):
        result = run_process(specification, tmp_path)
    with step_context("Проверить bounded RED и отсутствие detached потомка"):
        assert_equal(result.returncode, 124, "timeout return code")
        assert_contains("explicit 1-second local bound", result.stderr, "stderr")
        assert_true(result.duration_seconds < 5, "bounded timeout duration")
        _assert_detached_absent(evidence, "timeout")


@scenario(
    "LF-N42",
    "Отклонять command с пережившим detached потомком",
    feature="Владение командами",
)
def verify_process_descendant_rejection(tmp_path: Path) -> None:
    with step_context("Подготовить завершающийся command с detached потомком"):
        evidence = tmp_path / "leaked-descendant.json"
        specification = ProcessSpec(
            "descendant-tree",
            (sys.executable, "-I", "-B", "-c", DETACHED_PROGRAM, str(evidence), "exit"),
            timeout_seconds=10,
        )
    with step_context("Выполнить command через canonical public runner"):
        result = run_process(specification, tmp_path)
    with step_context("Проверить rejection и завершение detached потомка"):
        assert_equal(result.returncode, 126, "descendant return code")
        assert_contains("left a descendant process tree", result.stderr, "stderr")
        _assert_detached_absent(evidence, "normal command exit")


@scenario(
    "LF-N55",
    "Запрещать дочернему Python изменять запечатанный runtime",
    feature="Владение командами",
)
def verify_process_python_isolation(tmp_path: Path) -> None:
    with step_context("Запустить Python без явного флага -B через canonical runner"):
        specification = ProcessSpec(
            "python-isolation",
            (sys.executable, "-c", ISOLATION_PROGRAM),
            (("PYTHONDONTWRITEBYTECODE", "0"), ("PYTHONNOUSERSITE", "0")),
            timeout_seconds=10,
        )
        result = run_process(specification, tmp_path)
    with step_context("Проверить запрет bytecode и user-site на process boundary"):
        assert_equal(result.returncode, 0, "isolated Python return code")
        value = json.loads(result.stdout)
        assert_equal(value.get("bytecode_environment"), "1", "bytecode environment")
        assert_equal(value.get("dont_write_bytecode"), True, "bytecode disabled")
        assert_equal(value.get("no_user_site"), "1", "user site disabled")
