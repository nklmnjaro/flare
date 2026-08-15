import os
import selectors
import shlex
import signal
import subprocess
import sys
import time
from functools import partial
from pathlib import Path

import pytest

from tools.local_execution import clean_room as clean_room_module
from tools.local_execution import clean_room_source_supervisor as supervisor_module
from tools.local_execution import supervisor_client as supervisor_client_module
from tools.local_execution.clean_room import CleanRoomError, prove_clean_room
from tools.local_execution.clean_room_retention import PROOF_NAME
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_false,
    assert_raises,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import scenario, step_context

THREADED_DETACHED_PROGRAM = """\
import subprocess
import sys
import threading
import time
from pathlib import Path

def spawn() -> None:
    child = subprocess.Popen(
        ("/usr/bin/sleep", "300"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    Path(sys.argv[1]).write_text(str(child.pid), encoding="ascii")
    Path(sys.argv[2]).write_text(str(threading.get_native_id()), encoding="ascii")
    time.sleep(300)

thread = threading.Thread(target=spawn)
thread.start()
time.sleep(300)
"""
REPARENTED_DESCENDANT_PROGRAM = """\
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

signal.signal(signal.SIGCHLD, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()), encoding="ascii")
intermediate = '''
import os
import subprocess
import sys
import time
from pathlib import Path
child = subprocess.Popen(
    ("/usr/bin/sleep", "300"),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
Path(sys.argv[1]).write_text(str(child.pid), encoding="ascii")
Path(sys.argv[2]).write_text(str(os.getpid()), encoding="ascii")
while not Path(sys.argv[3]).exists():
    time.sleep(0.01)
'''
subprocess.Popen(
    (sys.executable, "-I", "-B", "-c", intermediate, *sys.argv[2:]),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
time.sleep(300)
"""


def _signal_zero(identifier: int) -> None:
    os.kill(identifier, 0)


def _process_state(identifier: int) -> str | None:
    try:
        raw = Path(f"/proc/{identifier}/status").read_text(encoding="ascii")
    except FileNotFoundError, ProcessLookupError:
        return None
    for line in raw.splitlines():
        if line.startswith("State:"):
            return line.split()[1]
    raise AssertionError(f"process state is incomplete: {identifier}")


def _wait_for_nonrunning(identifier: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if _process_state(identifier) in {None, "X", "Z"}:
            return
        time.sleep(0.01)
    try:
        os.kill(identifier, signal.SIGKILL)
    except ProcessLookupError:
        pass
    raise AssertionError(
        f"process remained executable after bounded cleanup: {identifier}"
    )


def _cleanup_fixture_processes(
    process: subprocess.Popen[bytes],
    *pid_paths: Path,
) -> None:
    for path in pid_paths:
        try:
            identifier = int(path.read_text(encoding="ascii").strip())
            group = os.getpgid(identifier)
            os.killpg(group, signal.SIGCONT)
            os.killpg(group, signal.SIGKILL)
        except FileNotFoundError, ProcessLookupError, PermissionError, ValueError:
            continue
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_for_nonempty(path: Path) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return
        time.sleep(0.01)
    raise AssertionError(f"process evidence was not published: {path}")


def _task_children(process: int, task: int) -> tuple[int, ...]:
    raw = Path(f"/proc/{process}/task/{task}/children").read_text(encoding="ascii")
    return tuple(int(value) for value in raw.split())


def _wait_for_fork(identifier: int) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        found, status = os.waitpid(identifier, os.WNOHANG)
        if found == identifier:
            return os.waitstatus_to_exitcode(status)
        time.sleep(0.01)
    os.kill(identifier, signal.SIGKILL)
    os.waitpid(identifier, 0)
    raise AssertionError(f"forked regression process did not exit: {identifier}")


def _detached_wait_command(
    pid_path: Path,
    shell_path: Path | None = None,
) -> tuple[str, ...]:
    shell_record = (
        ""
        if shell_path is None
        else f"printf '%s\\n' \"$$\" > {shlex.quote(os.fspath(shell_path))}; "
    )
    program = (
        shell_record + "/usr/bin/sleep 300 </dev/null >/dev/null 2>&1 & "
        f"printf '%s\\n' \"$!\" > {shlex.quote(os.fspath(pid_path))}; "
        "wait"
    )
    return "/usr/bin/setsid", "/bin/sh", "-c", program


def _write_noisy_public_fixture(root: Path) -> Path:
    root.mkdir(mode=0o700)
    (root / "Makefile").write_text(
        ".PHONY: check-fast\ncheck-fast:\n\t@./flare check-fast\n",
        encoding="utf-8",
    )
    (root / "source.txt").write_text("bounded output fixture\n", encoding="utf-8")
    flare = root / "flare"
    flare.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'case "${1:-}" in\n'
        "doctor)\n"
        "  /usr/bin/ps -o pgid= -p \"$$\" | /usr/bin/tr -d ' ' > command.pgid\n"
        "  /usr/bin/setsid /bin/sh -c '\n"
        "    /usr/bin/sleep 300 </dev/null >/dev/null 2>&1 &\n"
        '    printf "%s\\n" "$!" > descendant.pid\n'
        '    /usr/bin/ps -o pgid= -p "$!" | '
        '/usr/bin/tr -d " " > descendant.pgid\n'
        "  ' </dev/null >/dev/null 2>&1 &\n"
        "  while [ ! -s descendant.pid ]; do :; done\n"
        "  /usr/bin/head -c 600000 /dev/zero\n"
        "  /usr/bin/head -c 600000 /dev/zero >&2\n"
        "  touch noisy-output-completed\n"
        "  exit 1 ;;\n"
        "*) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    flare.chmod(0o755)
    subprocess.run(("git", "init", "-q"), cwd=root, check=True, timeout=10)
    subprocess.run(("git", "add", "-A"), cwd=root, check=True, timeout=10)
    uv = root.parent / "fixture-uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    return uv


@scenario(
    "LF-N35",
    "Ограничивать общий вывод public clean-room команды",
    feature="Воспроизводимость",
)
def verify_public_process_output_limit(tmp_path: Path) -> None:
    with step_context("Подготовить checkout с шумным процессом и долгим потомком"):
        source = tmp_path / "noisy-source"
        uv = _write_noisy_public_fixture(source)
        work_root = tmp_path / "noisy-proofs"
    with step_context("Выполнить public prove_clean_room до границы output bytes"):

        def run_proof() -> None:
            prove_clean_room(source, work_root, uv)

        error = assert_raises(
            CleanRoomError,
            run_proof,
            "public clean-room output limit",
        )
        assert_contains(
            "combined process output exceeded 1000000 bytes",
            str(error),
            "bounded output error",
        )
    with step_context("Проверить раннее завершение дерева без durable PASS"):
        pid_files = tuple(work_root.rglob("descendant.pid"))
        assert_true(bool(pid_files), "descendant PID evidence")
        assert_false(
            any(work_root.rglob("noisy-output-completed")),
            "command did not continue past the output boundary",
        )
        for pid_file in pid_files:
            identifier = int(pid_file.read_text(encoding="ascii").strip())
            command_group = (pid_file.parent / "command.pgid").read_text(
                encoding="ascii"
            )
            descendant_group = (pid_file.parent / "descendant.pgid").read_text(
                encoding="ascii"
            )
            assert_false(
                command_group == descendant_group,
                "descendant escaped the original process group",
            )
            assert_raises(
                ProcessLookupError,
                partial(_signal_zero, identifier),
                "noisy command descendant absent",
            )
        assert_false(any(work_root.rglob(PROOF_NAME)), "PASS not published")


@scenario(
    "LF-N37",
    "Завершать detached дерево при внутренней ошибке supervisor",
    feature="Воспроизводимость",
)
def verify_supervisor_capture_failure_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with step_context("Подготовить detached setsid потомка и forced capture failure"):
        pid_path = tmp_path / "capture-failure.pid"
        command = _detached_wait_command(pid_path)

        def fail_capture(
            _selector: selectors.BaseSelector,
            _buffers: dict[str, bytearray],
        ) -> bool:
            _wait_for_nonempty(pid_path)
            raise OSError("forced supervisor capture failure")

        monkeypatch.setattr(supervisor_module, "_capture_ready_output", fail_capture)
    with step_context("Выполнить supervisor failure в отдельном subreaper процессе"):
        child = os.fork()
        if child == 0:
            try:
                supervisor_module.supervise(command, 100)
            except OSError:
                os._exit(0)
            os._exit(92)
        child_exit = _wait_for_fork(child)
    with step_context("Проверить очистку detached потомка до возврата ошибки"):
        assert_equal(child_exit, 0, "capture failure subprocess exit")
        identifier = int(pid_path.read_text(encoding="ascii").strip())
        assert_raises(
            ProcessLookupError,
            partial(_signal_zero, identifier),
            "capture failure detached process absent",
        )


@scenario(
    "LF-N38",
    "Завершать detached дерево при прерывании parent execution",
    feature="Воспроизводимость",
)
def verify_parent_interruption_cleanup(tmp_path: Path) -> None:
    with step_context("Подготовить detached команду под public execution supervisor"):
        pid_path = tmp_path / "parent-interruption.pid"
        command = _detached_wait_command(pid_path)
    with step_context("Прервать parent во время ожидания supervisor"):
        child = os.fork()
        if child == 0:
            try:
                clean_room_module._execute(command, tmp_path, os.environ.copy(), 100)
            except KeyboardInterrupt:
                os._exit(0)
            os._exit(92)
        _wait_for_nonempty(pid_path)
        os.kill(child, signal.SIGINT)
        child_exit = _wait_for_fork(child)
    with step_context("Проверить cleanup handshake и отсутствие detached процесса"):
        assert_equal(child_exit, 0, "interrupted parent subprocess exit")
        identifier = int(pid_path.read_text(encoding="ascii").strip())
        assert_raises(
            ProcessLookupError,
            partial(_signal_zero, identifier),
            "interrupted parent detached process absent",
        )


@scenario(
    "LF-N39",
    "Принудительно очищать дерево зависшего supervisor",
    feature="Воспроизводимость",
)
def verify_stopped_supervisor_fallback(tmp_path: Path) -> None:
    with step_context("Запустить supervisor с detached setsid потомком"):
        pid_path = tmp_path / "stopped-supervisor.pid"
        command = _detached_wait_command(pid_path)
        process = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-B",
                os.fspath(clean_room_module.SUPERVISOR),
                "100",
                "--",
                *command,
            ),
            cwd=tmp_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    try:
        _wait_for_nonempty(pid_path)
        with step_context("Остановить supervisor и выполнить bounded proc fallback"):
            os.kill(process.pid, signal.SIGSTOP)
            supervisor_client_module.communicate_supervisor(process, 2)
        with step_context("Проверить завершение supervisor и detached потомка"):
            assert_true(process.poll() is not None, "stopped supervisor absent")
            identifier = int(pid_path.read_text(encoding="ascii").strip())
            _wait_for_nonrunning(identifier)
    finally:
        _cleanup_fixture_processes(process, pid_path)


@scenario(
    "LF-N45",
    "Очищать потомка, созданного не leader-thread процесса",
    feature="Воспроизводимость",
)
def verify_threaded_descendant_fallback(tmp_path: Path) -> None:
    with step_context("Запустить multithreaded command с detached потомком"):
        pid_path = tmp_path / "threaded-descendant.pid"
        task_path = tmp_path / "threaded-descendant.task"
        process = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-B",
                os.fspath(clean_room_module.SUPERVISOR),
                "100",
                "--",
                sys.executable,
                "-I",
                "-B",
                "-c",
                THREADED_DETACHED_PROGRAM,
                os.fspath(pid_path),
                os.fspath(task_path),
            ),
            cwd=tmp_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    try:
        _wait_for_nonempty(pid_path)
        _wait_for_nonempty(task_path)
        identifier = int(pid_path.read_text(encoding="ascii").strip())
        worker_task = int(task_path.read_text(encoding="ascii").strip())
        command = int(
            Path(f"/proc/{identifier}/status")
            .read_text(encoding="ascii")
            .split("PPid:\t", maxsplit=1)[1]
            .splitlines()[0]
        )
        assert_false(
            identifier in _task_children(command, command),
            "detached child is absent from the leader task children",
        )
        assert_true(
            identifier in _task_children(command, worker_task),
            "detached child belongs to the still-live worker task",
        )
        with step_context("Остановить subreaper и выполнить all-task fallback"):
            os.kill(process.pid, signal.SIGSTOP)
            supervisor_client_module.communicate_supervisor(process, 2)
        with step_context("Проверить отсутствие multithreaded descendant"):
            _wait_for_nonrunning(identifier)
    finally:
        _cleanup_fixture_processes(process, pid_path)


def _run_reparented_race(
    process: subprocess.Popen[bytes],
    paths: tuple[Path, Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    command_path, child_path, intermediate_path, release = paths
    for path in (command_path, child_path, intermediate_path):
        _wait_for_nonempty(path)
    command = int(command_path.read_text(encoding="ascii"))
    child = int(child_path.read_text(encoding="ascii"))
    intermediate = int(intermediate_path.read_text(encoding="ascii"))
    original = supervisor_module._direct_children
    released = False

    def release_after_snapshot(
        identifier: int,
        *,
        deadline: float | None = None,
        captured: set[int] | None = None,
        on_discovery: supervisor_module.DiscoveryHook | None = None,
    ) -> tuple[int, ...]:
        nonlocal released
        delayed_hook = None if identifier == command and not released else on_discovery
        observed = original(
            identifier,
            deadline=deadline,
            captured=captured,
            on_discovery=delayed_hook,
        )
        if identifier == command and not released:
            assert_true(intermediate in observed, "intermediate captured before exit")
            released = True
            release.touch()
            deadline = time.monotonic() + 5
            while (
                Path(f"/proc/{intermediate}").exists() and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert_false(Path(f"/proc/{intermediate}").exists(), "intermediate absent")
            if on_discovery is not None:
                for child in observed:
                    if child != intermediate:
                        on_discovery(child)
        return observed

    with monkeypatch.context() as scoped:
        scoped.setattr(supervisor_module, "_direct_children", release_after_snapshot)
        os.kill(process.pid, signal.SIGSTOP)
        supervisor_client_module.communicate_supervisor(process, 2)
    assert_true(released, "reparent race hook exercised")
    return child


@scenario(
    "LF-N47",
    "Пересканировать reparented потомка после исчезновения intermediate",
    feature="Воспроизводимость",
)
def verify_reparented_descendant_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_path = tmp_path / "reparent-command.pid"
    child_path = tmp_path / "reparent-child.pid"
    intermediate_path = tmp_path / "reparent-intermediate.pid"
    release = tmp_path / "reparent-release"
    process = subprocess.Popen(
        (
            sys.executable,
            "-I",
            "-B",
            os.fspath(clean_room_module.SUPERVISOR),
            "100",
            "--",
            sys.executable,
            "-I",
            "-B",
            "-c",
            REPARENTED_DESCENDANT_PROGRAM,
            *(
                os.fspath(path)
                for path in (command_path, child_path, intermediate_path, release)
            ),
        ),
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        child = _run_reparented_race(
            process,
            (command_path, child_path, intermediate_path, release),
            monkeypatch,
        )
        _wait_for_nonrunning(child)
    finally:
        _cleanup_fixture_processes(process, child_path, intermediate_path)


@scenario(
    "LF-N48",
    "Убивать известных потомков при ошибке финального proc rescan",
    feature="Воспроизводимость",
)
def verify_final_rescan_failure_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, child_path, shell_path = _start_detached_fixture(
        tmp_path,
        "final-rescan",
    )
    final_rescan = False
    try:
        original_stable = supervisor_client_module._stable_descendants
        original_descendants = supervisor_module.descendant_processes

        def mark_stable(
            root: int,
            captured: set[int],
            deadline: float,
        ) -> bool:
            nonlocal final_rescan
            result = original_stable(root, captured, deadline)
            final_rescan = True
            return result

        def fail_final_rescan(
            root: int,
            *,
            deadline: float | None = None,
            captured: set[int] | None = None,
            on_discovery: supervisor_module.DiscoveryHook | None = None,
        ) -> tuple[int, ...]:
            if final_rescan:
                raise supervisor_module.SupervisorError("forced final rescan failure")
            return original_descendants(
                root,
                deadline=deadline,
                captured=captured,
                on_discovery=on_discovery,
            )

        original_stop_state = supervisor_client_module._stop_state

        def fail_final_state(
            identifier: int,
            deadline: float | None = None,
        ) -> supervisor_module.StopState:
            if final_rescan:
                raise supervisor_client_module.SupervisorClientError(
                    "forced final state failure"
                )
            return original_stop_state(identifier, deadline)

        with monkeypatch.context() as scoped:
            scoped.setattr(supervisor_client_module, "_stable_descendants", mark_stable)
            scoped.setattr(
                supervisor_client_module,
                "descendant_processes",
                fail_final_rescan,
            )
            scoped.setattr(supervisor_client_module, "_stop_state", fail_final_state)
            os.kill(process.pid, signal.SIGSTOP)

            def communicate() -> None:
                supervisor_client_module.communicate_supervisor(process, 2)

            assert_raises(
                supervisor_client_module.SupervisorClientError,
                communicate,
                "forced final rescan failure",
            )
        assert_true(final_rescan, "final rescan fault exercised")
        _require_fixture_absent(process, child_path, shell_path)
    finally:
        _cleanup_fixture_processes(process, child_path, shell_path)


def _start_detached_fixture(
    tmp_path: Path,
    prefix: str,
) -> tuple[subprocess.Popen[bytes], Path, Path]:
    leaf_path = tmp_path / f"{prefix}-leaf.pid"
    shell_path = tmp_path / f"{prefix}-shell.pid"
    process = subprocess.Popen(
        (
            sys.executable,
            "-I",
            "-B",
            os.fspath(clean_room_module.SUPERVISOR),
            "100",
            "--",
            *_detached_wait_command(leaf_path, shell_path),
        ),
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _wait_for_nonempty(leaf_path)
    _wait_for_nonempty(shell_path)
    return process, leaf_path, shell_path


def _require_fixture_absent(
    process: subprocess.Popen[bytes],
    *pid_paths: Path,
) -> None:
    assert_true(process.poll() is not None, "supervisor process absent")
    for path in pid_paths:
        _wait_for_nonrunning(int(path.read_text(encoding="ascii").strip()))


@scenario(
    "LF-N49",
    "Сохранять partial PID при ошибке descendant scan",
    feature="Воспроизводимость",
)
def verify_partial_descendant_scan_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, leaf_path, shell_path = _start_detached_fixture(tmp_path, "partial")
    leaf = int(leaf_path.read_text(encoding="ascii").strip())

    def fail_after_capture(
        _root: int,
        *,
        deadline: float | None = None,
        captured: set[int] | None = None,
        on_discovery: supervisor_module.DiscoveryHook | None = None,
    ) -> tuple[int, ...]:
        if deadline is None or captured is None:
            raise AssertionError("cleanup scan omitted its deadline or PID registry")
        captured.add(leaf)
        if on_discovery is not None:
            on_discovery(leaf)
        raise supervisor_module.SupervisorError("forced partial scan failure")

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(
                supervisor_client_module,
                "descendant_processes",
                fail_after_capture,
            )
            os.kill(process.pid, signal.SIGSTOP)

            def communicate() -> None:
                supervisor_client_module.communicate_supervisor(process, 2)

            assert_raises(
                supervisor_client_module.SupervisorClientError,
                communicate,
                "partial descendant scan failure",
            )
        _require_fixture_absent(process, leaf_path, shell_path)
        started = time.monotonic()
        supervisor_client_module._force_cleanup(process)
        assert_true(time.monotonic() - started < 0.5, "idempotent cleanup bound")
    finally:
        _cleanup_fixture_processes(process, leaf_path, shell_path)


@scenario(
    "LF-N50",
    "Завершать дерево при BaseException после остановки supervisor",
    feature="Воспроизводимость",
)
def verify_post_stop_interruption_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, leaf_path, shell_path = _start_detached_fixture(tmp_path, "interrupt")
    original_signal = supervisor_client_module._signal
    shell = int(shell_path.read_text(encoding="ascii").strip())
    leaf = int(leaf_path.read_text(encoding="ascii").strip())
    interrupted = False

    def interrupt_after_stop(
        identifier: int,
        requested: signal.Signals,
    ) -> None:
        nonlocal interrupted
        original_signal(identifier, requested)
        if (
            identifier == process.pid
            and requested == signal.SIGSTOP
            and not interrupted
        ):
            interrupted = True
            original_signal(shell, signal.SIGSTOP)
            original_signal(leaf, signal.SIGSTOP)
            raise KeyboardInterrupt

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(
                supervisor_client_module,
                "_signal",
                interrupt_after_stop,
            )
            os.kill(process.pid, signal.SIGSTOP)

            def communicate() -> None:
                supervisor_client_module.communicate_supervisor(process, 2)

            assert_raises(
                KeyboardInterrupt,
                communicate,
                "post-stop interruption",
            )
        assert_true(interrupted, "post-stop interruption injected")
        _require_fixture_absent(process, leaf_path, shell_path)
    finally:
        _cleanup_fixture_processes(process, leaf_path, shell_path)


@scenario(
    "LF-N51",
    "Применять один deadline без задержки на каждый PID",
    feature="Воспроизводимость",
)
def verify_shared_cleanup_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    identifiers = tuple(range(10_000, 10_100))
    deadlines: set[float] = set()

    def descendants(
        _root: int,
        *,
        deadline: float | None = None,
        captured: set[int] | None = None,
        on_discovery: supervisor_module.DiscoveryHook | None = None,
    ) -> tuple[int, ...]:
        if deadline is None or captured is None:
            raise AssertionError("synthetic scan omitted its deadline or registry")
        deadlines.add(deadline)
        for identifier in identifiers:
            captured.add(identifier)
            if on_discovery is not None:
                on_discovery(identifier)
        return identifiers

    def stopped(_identifier: int, deadline: float | None = None) -> str:
        if deadline is None:
            raise AssertionError("synthetic state scan omitted its deadline")
        deadlines.add(deadline)
        return "stopped"

    with monkeypatch.context() as scoped:
        scoped.setattr(supervisor_client_module, "descendant_processes", descendants)
        scoped.setattr(supervisor_client_module, "_stop_state", stopped)
        scoped.setattr(supervisor_client_module, "_signal", lambda *_args: None)
        captured: set[int] = set()
        deadline = time.monotonic() + supervisor_module.SHUTDOWN_SECONDS
        started = time.monotonic()
        stable = supervisor_client_module._stable_descendants(
            9_999,
            captured,
            deadline,
        )
    assert_true(stable, "synthetic descendant set stabilized")
    assert_equal(captured, set(identifiers), "all synthetic descendants captured")
    assert_equal(deadlines, {deadline}, "one shared deadline")
    assert_true(
        time.monotonic() - started < 0.5, "cleanup scan independent of PID sleeps"
    )


@scenario(
    "LF-N53",
    "Продолжать source-supervisor finalizers после BaseException",
    feature="Воспроизводимость",
)
def verify_source_supervisor_finalizers(monkeypatch: pytest.MonkeyPatch) -> None:
    identifiers = {11_001, 11_002}
    signals: list[tuple[int, signal.Signals]] = []

    def fail_scan(
        _root: int,
        *,
        deadline: float | None = None,
        captured: set[int] | None = None,
        on_discovery: supervisor_module.DiscoveryHook | None = None,
    ) -> tuple[int, ...]:
        if deadline is None or captured is None:
            raise AssertionError("source cleanup omitted its deadline or registry")
        captured.update(identifiers)
        raise supervisor_module.SupervisorError("forced source scan failure")

    def record_signal(identifier: int, requested: signal.Signals) -> None:
        signals.append((identifier, requested))
        if len(signals) == 1:
            raise KeyboardInterrupt

    with monkeypatch.context() as scoped:
        scoped.setattr(supervisor_module, "descendant_processes", fail_scan)
        scoped.setattr(os, "kill", record_signal)
        assert_raises(
            supervisor_module.SupervisorError,
            supervisor_module._terminate_descendants,
            "source supervisor partial cleanup",
        )
    expected = {
        (identifier, requested)
        for identifier in identifiers
        for requested in (signal.SIGSTOP, signal.SIGKILL)
    }
    assert_equal(set(signals), expected, "all source finalizers attempted")


@scenario(
    "LF-N54",
    "Продолжать client finalizers после ошибки первого signal",
    feature="Воспроизводимость",
)
def verify_client_finalizers_after_signal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, leaf_path, shell_path = _start_detached_fixture(tmp_path, "finalizer")
    children = {
        int(path.read_text(encoding="ascii").strip())
        for path in (leaf_path, shell_path)
    }
    original_signal = supervisor_client_module._signal
    failed = False

    def fail_phase(
        _process: subprocess.Popen[bytes],
        captured: set[int],
        _deadline: float,
    ) -> None:
        captured.update(children)
        raise supervisor_module.SupervisorError("forced cleanup phase failure")

    def fail_first_signal(identifier: int, requested: signal.Signals) -> None:
        nonlocal failed
        if identifier in children and requested == signal.SIGSTOP and not failed:
            failed = True
            raise RuntimeError("forced descendant signal failure")
        original_signal(identifier, requested)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(supervisor_client_module, "_clean_stopped_tree", fail_phase)
            scoped.setattr(
                supervisor_client_module, "_final_descendant_scan", fail_phase
            )
            scoped.setattr(supervisor_client_module, "_signal", fail_first_signal)
            assert_raises(
                supervisor_client_module.SupervisorClientError,
                partial(supervisor_client_module._force_cleanup, process),
                "client finalizer signal failure",
            )
        assert_true(failed, "first descendant signal failed")
        _require_fixture_absent(process, leaf_path, shell_path)
    finally:
        _cleanup_fixture_processes(process, leaf_path, shell_path)
