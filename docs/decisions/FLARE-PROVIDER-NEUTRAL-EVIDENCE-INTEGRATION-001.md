# Flare Provider-Neutral Evidence Integration Boundary

**Decision ID:** `FLARE-PROVIDER-NEUTRAL-EVIDENCE-INTEGRATION-001`

**Product direction:** `ACCEPTED`

**Authority note:** repository acceptance is derived from canonical coordination
state rather than self-declared by this decision document.

**Decision date:** `2026-08-15`

**Product runtime authorization:** `NOT GRANTED`

## Decision

Flare is an independently deployable test-evidence and investigation service.
It integrates with delivery systems without replacing or owning their pipelines,
deployments, release lifecycle, or orchestration.

```text
Flare owns:
test evidence + investigation + live delivery + recovery/replay

Delivery systems own:
pipeline + deployment + release lifecycle + orchestration

Integration is:
versioned contracts + optional correlation metadata + adapters + stable links
```

The product must remain useful without any release platform:

```text
pytest plugin
→ versioned Flare ingestion API
→ durable canonical facts
→ PostgreSQL projection
→ SSE
→ Flare Web
```

External metadata enriches this flow but is not required for it.

## Core boundary

Core contracts use provider-neutral concepts such as:

```text
ScmContext
CiContext
ReleaseContext
DeploymentContext
ExternalReference
CorrelationMetadata
```

Provider-specific environment variables, models, clients, and lifecycle logic
must not enter core. Examples include GitLab tokens and pipeline identifiers,
Jenkins build models, DPM release models, Kubernetes deployment models, and
Mattermost message models.

Core may retain an external provider label, external identifier, stable URL,
and correlation metadata. That reference does not transfer ownership of the
external resource to Flare.

## Adapter boundary

Provider adapters live outside core and translate external representations into
canonical Flare contracts. They form small anti-corruption layers for concrete
consumers, not a generic plugin framework.

An adapter is introduced only when a live consumer and a verifiable end-to-end
scenario exist. GitLab, Jenkins, GitHub, Platform V DPM, Kubernetes, Mattermost,
and future systems are independent adapters rather than core dependencies.

## Stable integration seams

The initial supported seams are deliberately small:

1. A versioned inbound HTTP ingestion API.
2. Versioned outbound webhook or event delivery.
3. Stable deep links for sessions, tests, failures, and evidence.

SDKs, broker-based delivery, subscriptions, connector marketplaces, and dynamic
plugin runtimes require separate evidence-backed decisions.

## Failure semantics

Integration must degrade without coupling availability or creating duplicate
domain entities:

- if Flare is unavailable, external pipelines and releases continue and expose
  evidence status as unavailable;
- if a release cockpit is unavailable, Flare continues accepting evidence and
  correlation can be reconciled later;
- lost outbound delivery is recovered through idempotent API reconciliation;
- retries do not create duplicate Flare sessions, external releases, or
  deployments.

## First product proof

The first product vertical remains one real end-to-end behavior:

```text
pytest emits SESSION_STARTED
→ server durably accepts it
→ PostgreSQL stores the canonical fact
→ projector builds an investigation view
→ browser shows the active session
→ optional external metadata appears as a stable link
```

This decision does not authorize implementation of that vertical. It defines
the boundary that a later accepted Protocol Seed and product Change must obey.

## Explicit non-goals

Do not introduce without a separate accepted decision and demonstrated need:

```text
release orchestration in Flare
workflow DSL
generic integration framework
dynamic plugin registry
universal connector SDK
Kubernetes operator for integrations
migration of existing pipelines into Flare
microservice decomposition
AI as an independent product moat
```

## Roadmap consequence

Finish and accept the current Quality and Local-First foundation before product
growth. Then freeze generic `tools/**` expansion, establish the Protocol Seed,
prove the first vertical, add provider-neutral correlation metadata, and use a
real release cockpit as a design partner. Implement the first provider adapter
only after the vertical has a live consumer.

## Outcome measures

Product value is measured by investigation and adoption outcomes, including:

- median time from failure to understood cause;
- human minutes per investigation;
- proportion of runs with complete evidence;
- unnecessary reruns;
- actionable-failure rate;
- recovery success after reconnect or restart;
- time required to connect an existing CI system.

Integration count and dashboard breadth are not primary success measures.
