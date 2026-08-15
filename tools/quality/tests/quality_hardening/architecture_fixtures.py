from dataclasses import dataclass

from tools.quality.test_architecture_policy import TestRule


@dataclass(frozen=True, slots=True)
class ArchitectureCase:
    label: str
    path: str
    source: str
    expected_rules: tuple[TestRule, ...]


_QUALITY_ROOT = "tools/quality/tests/quality_hardening/"

ARCHITECTURE_CASES = (
    ArchitectureCase(
        "sync-pytest-entrypoint",
        f"{_QUALITY_ROOT}test_sync.py",
        "def test_sync(tmp_path):\n    value = tmp_path.name\n    print(value)\n",
        (),
    ),
    ArchitectureCase(
        "async-pytest-entrypoint",
        f"{_QUALITY_ROOT}test_async.py",
        "async def test_async():\n    await operation()\n",
        (),
    ),
    ArchitectureCase(
        "parametrized-test",
        f"{_QUALITY_ROOT}test_parameter.py",
        "import pytest\n\n@pytest.mark.parametrize('value', [1, 2])\n"
        "def test_value(value):\n    check_equal(value, value)\n",
        (),
    ),
    ArchitectureCase(
        "fixture-and-yield-fixture",
        f"{_QUALITY_ROOT}conftest.py",
        "import pytest\n\n@pytest.fixture\ndef value():\n    return 1\n\n"
        "@pytest.fixture\ndef resource():\n    yield object()\n",
        (),
    ),
    ArchitectureCase(
        "nested-assertions-boundary",
        f"{_QUALITY_ROOT}nested/assertions.py",
        "def check(value):\n    assert value\n",
        (),
    ),
    ArchitectureCase(
        "nested-reporting-boundary",
        f"{_QUALITY_ROOT}nested/reporting.py",
        "import allure as report\nfrom allure_commons import plugin_manager\n",
        (),
    ),
    ArchitectureCase(
        "legitimate-pytest-constructs",
        f"{_QUALITY_ROOT}test_legitimate.py",
        "import pytest\n\nclass TestGroup:\n"
        "    @pytest.mark.usefixtures('resource')\n"
        "    def test_case(self):\n        check_equal(1, 1)\n",
        (),
    ),
    ArchitectureCase(
        "suppression-like-prose",
        f"{_QUALITY_ROOT}support.py",
        "TEXT = '# ruff: noqa and # mypy: ignore-errors are documentation'\n"
        "# ruff noqa\n# mypy ignore-errors\n",
        (),
    ),
    ArchitectureCase(
        "raw-assert-entrypoint",
        f"{_QUALITY_ROOT}test_bad.py",
        "def test_bad():\n    assert True\n",
        (TestRule.RAW_ASSERT,),
    ),
    ArchitectureCase(
        "raw-assert-support",
        f"{_QUALITY_ROOT}support.py",
        "def check(value):\n    assert value\n",
        (TestRule.RAW_ASSERT,),
    ),
    ArchitectureCase(
        "unittest-import",
        f"{_QUALITY_ROOT}test_bad.py",
        "import unittest\n",
        (TestRule.UNITTEST,),
    ),
    ArchitectureCase(
        "nested-unittest-mock-import",
        f"{_QUALITY_ROOT}support.py",
        "def helper():\n    from unittest.mock import patch\n    return patch\n",
        (TestRule.UNITTEST,),
    ),
    ArchitectureCase(
        "direct-allure-import",
        f"{_QUALITY_ROOT}test_bad.py",
        "import allure\n",
        (TestRule.DIRECT_ALLURE,),
    ),
    ArchitectureCase(
        "aliased-allure-commons-import",
        f"{_QUALITY_ROOT}support.py",
        "import allure_commons as reporting\n",
        (TestRule.DIRECT_ALLURE,),
    ),
    ArchitectureCase(
        "nested-allure-import",
        f"{_QUALITY_ROOT}support.py",
        "def helper():\n    from allure import step as report_step\n"
        "    return report_step\n",
        (TestRule.DIRECT_ALLURE,),
    ),
    ArchitectureCase(
        "direct-typing-cast",
        f"{_QUALITY_ROOT}support.py",
        "from typing import cast\nvalue = cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "aliased-typing-extensions-cast",
        f"{_QUALITY_ROOT}support.py",
        "from typing_extensions import cast as convert\nvalue = convert(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "module-qualified-cast",
        f"{_QUALITY_ROOT}support.py",
        "import typing as types\nvalue = types.cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "assigned-module-qualified-cast",
        f"{_QUALITY_ROOT}support.py",
        "import typing\ncoerce = typing.cast\nvalue = coerce(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "assigned-typing-module-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing\napi = typing\nvalue = api.cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "annotated-typing-module-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing\napi: int = typing\nvalue = api.cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "chained-typing-module-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing\napi = typing\nfacade = api\nvalue = facade.cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "assigned-typing-extensions-module-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing_extensions\napi = typing_extensions\n"
        "value = api.cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "shadowed-typing-module-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing as api\napi = object()\nvalue = api.cast(int, source)\n",
        (),
    ),
    ArchitectureCase(
        "cleared-assigned-typing-module-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing\napi = typing\napi = object()\nvalue = api.cast(int, source)\n",
        (),
    ),
    ArchitectureCase(
        "conditional-clear-keeps-possible-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing\napi = typing\nif flag:\n    api = object()\n"
        "value = api.cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "loop-clear-keeps-possible-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing\napi = typing\nfor item in values:\n    api = item\n"
        "value = api.cast(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "unrelated-cast-attribute",
        f"{_QUALITY_ROOT}support.py",
        "api = object()\nvalue = api.cast(int, source)\n",
        (),
    ),
    ArchitectureCase(
        "parameter-shadow-after-assigned-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing\napi = typing\n\ndef helper(api):\n"
        "    return api.cast(int, source)\n",
        (),
    ),
    ArchitectureCase(
        "function-local-shadow-after-import",
        f"{_QUALITY_ROOT}support.py",
        "def helper():\n    import typing as api\n    api = object()\n"
        "    return api.cast(int, source)\n",
        (),
    ),
    ArchitectureCase(
        "lambda-shadowed-typing-module-alias",
        f"{_QUALITY_ROOT}support.py",
        "import typing as api\nvalue = (lambda api: api.cast(int, source))(obj)\n",
        (),
    ),
    ArchitectureCase(
        "nested-cast-import",
        f"{_QUALITY_ROOT}support.py",
        "def helper():\n    from typing import cast as convert\n"
        "    return convert(int, source)\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "nested-import-alias-collision",
        f"{_QUALITY_ROOT}support.py",
        "def bad():\n"
        "    import typing as types\n"
        "    return types.cast(int, source)\n\n"
        "def safe():\n"
        "    import decimal as types\n"
        "    return types.Decimal('1')\n",
        (TestRule.TYPE_CAST,),
    ),
    ArchitectureCase(
        "ruff-suppression",
        f"{_QUALITY_ROOT}support.py",
        "value = missing_name  # noqa: F821\n",
        (TestRule.SUPPRESSION,),
    ),
    ArchitectureCase(
        "mypy-file-suppression",
        f"{_QUALITY_ROOT}support.py",
        "# mypy: ignore-errors\nvalue: int = 'bad'\n",
        (TestRule.SUPPRESSION,),
    ),
    ArchitectureCase(
        "mypy-inline-suppression",
        f"{_QUALITY_ROOT}support.py",
        "value: int = 'bad'  # type: ignore[assignment]\n",
        (TestRule.SUPPRESSION,),
    ),
)
