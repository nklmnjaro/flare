from collections.abc import Callable


def assert_true(value: bool, label: str) -> None:
    assert value, f"Expected true: {label}"


def assert_false(value: bool, label: str) -> None:
    assert not value, f"Expected false: {label}"


def assert_equal[T](actual: T, expected: T, label: str) -> None:
    assert actual == expected, f"Expected {label}={expected!r}; actual={actual!r}"


def assert_contains(needle: str, value: str, label: str) -> None:
    assert needle in value, f"Expected {needle!r} in {label}; actual={value[:800]!r}"


def assert_not_contains(needle: str, value: str, label: str) -> None:
    assert needle not in value, (
        f"Expected {needle!r} absent from {label}; actual={value[:800]!r}"
    )


def assert_raises[E: BaseException](
    exception: type[E],
    operation: Callable[[], None],
    label: str,
) -> E:
    try:
        operation()
    except exception as error:
        return error
    raise AssertionError(f"Expected {exception.__name__} from {label}")
