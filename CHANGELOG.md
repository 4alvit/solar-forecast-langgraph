# Changelog

## [0.1.9] - Unreleased

### Fixed

- Preserve sky-diffuse irradiance when projecting horizontal weather radiation
  onto solar panels. Horizontal panels now retain the full global irradiance,
  and tilted panels use standard isotropic sky and ground view factors.
- Clarify that Open-Meteo `direct_radiation` is horizontal direct radiation;
  retain the historical `dni` argument and trained feature name for compatibility.
  Cloud attenuation is still applied only by the weather provider.

### Upgrade

Eight synthetic reference cases match pvlib 0.13.1 isotropic transposition,
including diffuse-only, back-facing, vertical and near-horizon panels. Tests
also cover the weather adapter through every unfitted forecast method. This
checks the calculation, not forecast accuracy at a real installation. No
configuration or trained feature-schema migration is required. Keep the prior
accepted package for rollback; beta publication does not deploy services or
replace the stable PyPI package.

### Security

Update the locked certifi trust bundle to 2026.10.19 to resolve the critical
advisory reported by the required dependency scan. Existing TLS, dependency
checks and source-bound release verification remain enabled. Radiation tests
use synthetic local data and do not access a live site or credentials.

## [0.1.8] - 2026-10-18

### Changed

- Refresh pinned shared review, merge and RC fuzzing workflows while preserving the required CI gates.

### Upgrade

This is a maintenance release with no configuration or data migration. Preserve installation-specific configuration and retain the previous package for rollback.

### Security

Required CI, dependency checks and source-bound RC qualification remain enabled. No additional runtime security fix is claimed.

## [0.1.7] - 2026-10-17

### Changed

- Clarify where RC fuzz safeguards execute and link the shared illustrated process and result guides; these documentation links were added after the published v0.1.6 source.

### Upgrade

This documentation release preserves runtime behavior and configuration from 0.1.6. Retain site configuration, broker credentials and the previous accepted package for rollback.

### Security

No new runtime security fix is claimed. Existing TLS checks and source-bound RC fuzzing remain required; live site and broker acceptance remains deployment-specific.

## [0.1.6] - 2026-10-14

### Changed

- Validate each public release candidate with bounded, network-isolated fuzz campaigns against its exact source revision.
- Require positive engine execution counts, instrumented production code and validated seed corpora; retain source-bound reports and diagnostic evidence.
- Run deterministic seed and configuration checks in ordinary CI without starting mutation campaigns on betas.

### Upgrade

Use the existing installation procedure, preserve local configuration and keep the previous accepted package for rollback. This maintenance release updates release validation and does not change the application configuration format. Deployment and applicable device or integration acceptance remain separate from publication.

### Security

RC publication rejects absent or invalid source-bound fuzz reports. The fuzz runner bounds corpus paths, file types and size. No application vulnerability or new target-device acceptance is claimed by these tooling changes.

## [Unreleased]

### Security

- Close the owned TLS socket on a fatal native handshake error while retaining
  sockets when a nonblocking handshake requests another read or write.
- Apply verified certificate-chain key minima to optional LLM API calls and close their HTTP connection pool on completion or failure.

### Changed

- Document project governance, conduct, roadmap and OpenSSF assessment evidence.
- Treat unexpected Python test warnings as failures.


## [0.1.5]

### Fixed

Reject nonfinite panel configuration values, including overflowing JSON capacity
exponents, before forecast calculations or JSON serialization. Existing finite
configuration values and their round trips remain unchanged.

### Changed

Start the next beta cycle after the published 0.1.4 release. This candidate includes explicit HTTPX TLS configuration, platform certificate handling, CLI version reporting, and stricter artifact and publication verification added since 0.1.4.

### Upgrade

Keep using the published stable package unless testing this beta. Preserve site coordinates, broker credentials and local certificate settings; review the documented TLS policy when testing deployments. Beta publication does not update the stable PyPI package or deploy services.

### Security

TLS and release checks remain enabled. This version change opens a new immutable release series and does not itself claim to fix an additional vulnerability.

## [0.1.4]

### Changed

Document contributor validation, private vulnerability reporting and deployment boundaries for the OpenMeteo/LangGraph forecasting workflow. Release publication now includes source-bound human change notes together with the existing artifact provenance.

### Upgrade

The forecast/MQTT interface is unchanged by this documentation and release-tooling update. Keep site coordinates, MQTT credentials and broker transport settings private; use the documented locked dependency installation.

### Security

No application vulnerability is claimed fixed by this documentation update. Release tooling rejects absent, ambiguous or malformed change notes before publishing a tag, so a build cannot silently omit required upgrade and security guidance.

