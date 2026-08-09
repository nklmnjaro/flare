import { readFileSync } from "node:fs";

const configuredPythonVersion = readFileSync(
  new URL("../../../../.python-version", import.meta.url),
  "utf8",
).trim();

const hasLabel = (labels, name, value) =>
  labels.some((label) => label.name === name && label.value === value);

export default {
  name: "Flare A.1 Coordination State",
  plugins: {
    awesome: {
      options: {
        groupBy: ["parentSuite", "suite", "subSuite"],
      },
    },
  },
  variables: {
    "Change": "FLARE-TRACK-A1-COORDINATION-STATE-001",
    "Contract baseline": "f7db10c0301a5693fdcce1e945040672188a2343",
    "Python target (configured)": configuredPythonVersion,
    "Scenario contract": "A1-N01 through A1-N32",
    "Test scheduler (configured)": `pytest-xdist ${process.env.STATE_TEST_WORKERS ?? "4"} workers, worksteal distribution`,
    "Validation pipeline": "bytes → strict JSON → JSON Schema → typed model → semantics → projection → CAS",
    "Evidence policy": "bounded attachments owned by the producing step or fixture",
  },
  environments: {
    "isolated-git": {
      name: "Isolated Git candidate repositories",
      matcher: ({ labels }) => hasLabel(labels, "test_environment", "isolated-git"),
      variables: {
        "Repository lifecycle": "fresh local Git repository per scenario",
        "Candidate identity": "immutable full commit OID",
        "Publication primitive": "git update-ref <new> <old> compare-and-swap",
      },
    },
    "pure-model": {
      name: "Pure typed-model checks",
      matcher: ({ labels }) => hasLabel(labels, "test_environment", "pure-model"),
      variables: {
        "Repository lifecycle": "not required",
        "Execution model": "in-process immutable value objects",
        "Primary proof": "review payload and assignment identity hashes",
      },
    },
  },
  allowedEnvironments: ["isolated-git", "pure-model"],
  hideLabels: ["package", "host", "thread", "test_environment"],
};
