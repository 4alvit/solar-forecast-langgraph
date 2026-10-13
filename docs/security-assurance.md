# Security assurance and evidence limits

Assessment date: 2026-10-13. Application evidence was collected from source `65a2c87d3e98f3f4e2cf8c10a11ff8665c7145ea`. The threat model assumes a maintained Python runtime, trusted host/configuration, and operators who control deployment credentials. The claim is bounded risk reduction through concrete controls and tests, not a formal security certification.

## Data flow and trust boundaries

The CLI loads a trusted local Python configuration, fetches weather/history, runs physical/statistical models through LangGraph and writes forecasts. Optional MQTT publishes forecast summaries and pre-charge requests. Configuration files are executable Python: never load a configuration received from an untrusted party. Remote history and weather are untrusted data; they are not authorization for physical actuation.

`httpx_tls.py` supplies per-client HTTPX transports preserving configured trust sources and proxy selection. `tls_policy.py` retains ordinary chain/hostname validation and checks every verified certificate key before application data, with TLS 1.2 minimum and RSA keys of at least 2048 bits. The actual transport tests include loopback TLS failures and successful strong-key connections. See [TLS policy](tls-policy.md). These guarantees apply to HTTPS; local HTTP defaults and the MQTT delivery adapter are plaintext. Use an isolated trusted network or external authenticated TLS tunnel for MQTT; this project does not claim encryption for every network path.

There is no local external-user authentication or password-verifier store. Configured remote service tokens are client credentials and must remain outside version control. The optional LLM client receives the same verified HTTPX transport; actual SDK loopback tests check that weak roots, untrusted chains and wrong hostnames block API-token transmission. Forecast confidence and synthetic unit tests are not measured forecast accuracy. [Forecast validation](forecast-validation.md) describes the missing field benchmark; [MQTT delivery](mqtt-delivery.md) distinguishes broker acknowledgement from safe physical action.

## Static analysis triage

The application-only Bandit 1.8.6 scan on 2026-10-13 found no findings at any severity and no scanner errors. This is evidence for the inspected source, not proof that all vulnerabilities are absent.

## Verification argument

The [automated tests](../tests) exercise configuration, failure paths, transport validation and behavior. [scripts/ci.sh](../scripts/ci.sh) runs locked dependency installation, Ruff, format checks, mypy and pytest with coverage. The public quality gate additionally requires workflow/release contracts, CodeQL, dependency review and security scanning. Source inspection and regression tests complement these checks; they are not an independent penetration test.

The 2026-10-13 authenticated GitHub review found zero open dependency alerts, secret alerts or repository security advisories. Four open code-scanning results are Scorecard process findings for best-practices enrollment, maintenance history, fuzzing and branch protection, not identified application vulnerabilities. They remain visible; no protection or security gate is weakened to improve a score. [Public evidence](evidence/assessment-2026-10-13.json) records exact counts, source and local results. Later alerts and versions require a new review.

Published downloads use GitHub HTTPS and SHA-256 inventory. Checksums and a publisher manifest are not independent digital signatures. Signed-release and reproducible-build criteria remain unclaimed until exact published assets are independently verified. The Dockerfile runs as a non-root user; no complete ELF/runtime-hardening audit or accessibility audit is claimed by that fact alone.

## Maintenance commitments and unresolved assumptions

New security-sensitive behavior requires normal, invalid-input and authorization/failure-path tests. Confirmed defects follow [SECURITY.md](../SECURITY.md), including confidential coordination and release notes. Credit reporters in advisories and release notes with their consent; respect anonymous reporting. Dependency changes use the lock file and required checks rather than unreviewed floating deployment updates.

The owner confirmed secure-design and common Python/network-vulnerability knowledge and no external bug, enhancement or vulnerability reports in the preceding 12 months for this project on 2026-10-13. Public issue and advisory review is recorded separately in the evidence. There is no verified successor or recovery arrangement: [GOVERNANCE.md](../GOVERNANCE.md) leaves Silver continuity unmet.

## Coverage scope

The combined application and release/workflow/security tests cover 1849 of 2826 executable statements across all tracked non-test Python files (65.43%). Previously unmeasured Python files receive zero credit. Shell, Docker and workflow-language statements are not measured by this figure. The Silver whole-project 80% criterion remains unmet.
