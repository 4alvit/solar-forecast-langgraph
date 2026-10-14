# Changelog

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

