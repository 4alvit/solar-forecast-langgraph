# Roadmap and current status

This roadmap records direction rather than promised delivery dates. Propose priorities through [issues](https://github.com/4alvit/solar-forecast-langgraph/issues); decisions follow [GOVERNANCE.md](GOVERNANCE.md).

## Delivered and verified

The repository contains a solar forecast workflow with optional MQTT delivery, a locked Python dependency graph, automated tests, lint/type checks, CodeQL, dependency review and a gated candidate-to-stable release process. [CHANGELOG.md](CHANGELOG.md) records versioned changes; [quality and assurance](docs/security-assurance.md) records evidence and its limits. A passing test suite is not evidence of production or hardware acceptance.

## Next priorities

1. Build the public, chronological forecast evaluation described in [forecast-validation.md](docs/forecast-validation.md), including immutable input data, baselines and honest error metrics.
2. Preserve nonblocking model training and bounded MQTT acknowledgement behavior; require actuator-side safety and deduplication before automatic charging.
3. Establish exact-release acceptance for both supported OCI architectures and independently verifiable release signatures.
4. Establish a real backup maintainer or tested recovery arrangement for repository, CI, publication and confidential security reports. Until then OpenSSF Silver continuity is unmet.
5. Expand whole-project coverage and measure reproducibility, accessibility and runtime hardening before claiming those criteria. Unit tests do not substitute for fuzzing or a penetration test.

Review this roadmap when releasing or materially changing architecture. Completed work belongs in the changelog with reproducible evidence; remove obsolete plans explicitly rather than silently treating them as delivered.
