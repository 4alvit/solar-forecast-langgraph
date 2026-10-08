# SPDX-License-Identifier: MIT
# Copyright (c) 2026 victron-venus
# Adapted from inverter-dashboard TLS policy; see docs/tls-policy.md.
"""HTTPX client with unchanged routing and exact peer/proxy key checks."""

import httpcore
import httpx
from httpx._utils import get_environment_proxies

from .tls_policy import enforce_peer_key_policy


def async_client(*, timeout: float) -> httpx.AsyncClient:
    """Retain HTTPX trust sources, environment proxy selection and default limits."""
    context = enforce_peer_key_policy(httpx.create_ssl_context())
    mounts: dict[str, httpx.AsyncHTTPTransport | None] = {}
    for pattern, url in get_environment_proxies().items():
        if url is None:
            mounts[pattern] = None
            continue
        proxy = httpx.Proxy(url)
        if proxy.url.scheme == "https":
            # HTTPcore uses its certifi context for HTTPS proxies, independently
            # of the origin's SSL_CERT_FILE/SSL_CERT_DIR environment selection.
            proxy.ssl_context = enforce_peer_key_policy(httpcore.default_ssl_context())
        mounts[pattern] = httpx.AsyncHTTPTransport(
            proxy=proxy,
            verify=context,
            trust_env=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return httpx.AsyncClient(verify=context, mounts=mounts, trust_env=False, timeout=timeout)
