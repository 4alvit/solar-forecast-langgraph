# TLS certificate key policy

Owned TLS contexts retain CA and hostname verification and inspect the actual
verified chain, including its selected trust anchor, before application data.
RSA moduli must contain at least 2048 significant bits; EC keys need at least
224 bits; DSA requires p >= 2048 and q >= 224. Ed25519 and Ed448 are accepted.
Unknown algorithms or runtimes without an accessible verified chain fail closed.
OpenSSL security level 2 alone can accept a 2047-bit RSA modulus.

CPython 3.11 and 3.12 use the private `_sslobj.get_verified_chain` interface;
newer CPython versions may expose the public equivalent. This runtime contract
is tested rather than inferred from the Python version. Alternative Python
implementations are not implicitly supported.

The public-key decoder uses cryptography except on Intel macOS, where the
native Security framework reads key metadata without changing trust decisions.
The Intel backend accepts RSA and EC only. No system trust store is modified.

The TLS policy and Darwin metadata decoder are adapted from the MIT-licensed
victron-venus/inverter-dashboard implementation, copyright 2026 victron-venus.
The project MIT license also applies to these adaptations. This policy does
not establish the strength of inbound TLS terminators or unrelated transports.

## Forecast and history HTTPS

OpenMeteo and the Monitoring, InfluxDB and Prometheus history clients use the
owned HTTPX client. Origin CA selection still follows HTTPX's certifi default
or SSL_CERT_FILE / SSL_CERT_DIR. HTTPS proxy trust still uses HTTPcore's
separate certifi default. HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and NO_PROXY routing
is preserved, including exclusions; proxy TLS is checked before CONNECT or
proxy credentials. HTTPX's default limits, timeouts, redirect and retry behavior
remain unchanged. HTTPX and HTTPcore are pinned because the environment routing
helper is private and covered by regression tests.

The optional OpenAI/LangChain client is a separate transport which this change
does not configure. MQTT delivery and external ingress also require their own
assessment. This is not a project-wide OpenSSF key-length attestation.
