from dataclasses import dataclass
from enum import StrEnum


class CheckStatus(StrEnum):
    PASS = "PASS"
    OPTIONAL_MISSING = "OPTIONAL_MISSING"
    FAIL = "FAIL"


class Capability(StrEnum):
    DOCTOR = "doctor"
    BOOTSTRAP = "bootstrap"
    CHECK_FAST = "check-fast"
    CHECK = "check"
    VERIFY = "verify"
    DIAGNOSE = "diagnose"
    STATE_CHECK = "state-check"
    STATE_STATIC = "state-static"
    STATE_TEST = "state-test"
    STATE_ALLURE = "state-allure"
    STATE_ALLURE_OPEN = "state-allure-open"
    ENVIRONMENT_MANIFEST = "environment-manifest"


PUBLIC_CAPABILITIES = (
    Capability.DOCTOR,
    Capability.BOOTSTRAP,
    Capability.CHECK_FAST,
    Capability.CHECK,
    Capability.VERIFY,
    Capability.DIAGNOSE,
)


@dataclass(frozen=True, slots=True)
class Observation:
    name: str
    status: CheckStatus
    detail: str
    required: bool

    def render(self) -> str:
        requirement = "required" if self.required else "optional"
        return f"{self.name}={self.status.value} {requirement} {self.detail}"


@dataclass(frozen=True, slots=True)
class DoctorReport:
    profile_id: str
    observations: tuple[Observation, ...]

    @property
    def passed(self) -> bool:
        return not any(
            item.required and item.status is CheckStatus.FAIL
            for item in self.observations
        )

    def render(self) -> str:
        lines = [f"profile={self.profile_id}"]
        lines.extend(item.render() for item in self.observations)
        lines.append(f"doctor={'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    label: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    status: CheckStatus
    action: str
    detail: str
    manifest_sha256: str | None

    @property
    def passed(self) -> bool:
        return self.status is CheckStatus.PASS
