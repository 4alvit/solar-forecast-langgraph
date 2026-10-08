# Changelog

## [0.1.4]

### Changed

Document contributor validation, private vulnerability reporting and deployment boundaries for the OpenMeteo/LangGraph forecasting workflow. Release publication now includes source-bound human change notes together with the existing artifact provenance.

### Upgrade

The forecast/MQTT interface is unchanged by this documentation and release-tooling update. Keep site coordinates, MQTT credentials and broker transport settings private; use the documented locked dependency installation.

### Security

No application vulnerability is claimed fixed by this documentation update. Release tooling rejects absent, ambiguous or malformed change notes before publishing a tag, so a build cannot silently omit required upgrade and security guidance.

