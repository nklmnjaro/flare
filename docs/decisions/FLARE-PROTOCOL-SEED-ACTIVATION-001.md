---
decision_id: "FLARE-PROTOCOL-SEED-ACTIVATION-001"
status: "OPEN"
---

# Flare Protocol Seed activation

The Quality and Local-First foundation may be accepted independently of product
runtime. Foundation acceptance does not authorize the Protocol Seed, the first
product vertical, production, or release work.

The next technical decision is to accept the smallest executable Product Change
contract for the Protocol Seed. That contract must define only the shared
provider-neutral envelope and identity semantics required by the first real
vertical, including:

- event and schema version identity;
- event, session, and correlation identifiers;
- timestamps and idempotency identity;
- optional provider-neutral external references;
- compatibility and rejection semantics.

It must not introduce provider models, a generic integration framework, a
broker, a workflow DSL, a connector SDK, release orchestration, or product
runtime before those scopes are separately authorized.

This decision closes when Product Owner accepts an exact Protocol Seed Change
contract with executable acceptance criteria. Until then there is no safe active
Product Change after foundation acceptance.
