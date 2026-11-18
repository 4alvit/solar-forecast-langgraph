# Documentation

A LangGraph service that produces solar forecasts for a Victron installation and
delivers them over MQTT, with the evaluation and release records around it.

## Understand it

- [Distribution channels](distribution-channels.md) — the stable and prerelease channels as of 3 November 2026.
- [Controller delivery v1](mqtt-delivery.md) — which broker `MQTT_BROKER` must point at, and why not the container's own.
- [Forecast evidence and evaluation](forecast-validation.md) — how `solar-forecast-evaluate` records forecasts and later observations.

## Release operation

- [CI and release operations](release-workflow.md) — `.release-policy.json` and the required status.
- [CI orchestration](CI-ORCHESTRATION.md) — how quality gate and release pipeline divide the events.
- [Project release packaging and versions](release-packaging.md) — the archive, wheel, sdist and amd64/arm64 image.
- [Version plans and manifest synchronization](VERSIONING.md) — the versioning opt-in.
- [Release helper TLS profile](RELEASE_TLS_PROFILE.md) — the qualified `gh` transport profile.

## Evidence

- [Security assurance and evidence limits](security-assurance.md) — the 2026-10-13 assessment and the tooling it includes.
- [TLS certificate key policy](tls-policy.md) — the verification applied to owned HTTPS clients.
- [OpenSSF Best Practices evidence](openssf-evidence.md) — the evidence index behind the self-assessment.
- [Release-candidate fuzz testing](fuzzing.md) — the illustrated RC fuzzing process.
- [Fuzzing release candidates](rc-fuzzing.md) — the reusable bounded fuzz workflow.
- [Release read recovery and rerun validation](release-read-safety.md) — the two fixes carried from the shared toolkit.
- [Early final-build runner check](runner-preflight.md) — why the check runs before the final build.
