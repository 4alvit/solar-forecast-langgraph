"""Real owned HTTPX and application-client TLS/proxy contracts."""

import ssl
from datetime import UTC, datetime
from inspect import unwrap

import httpx
import pytest
from test_tls_policy import CHAIN_CASES, calibrate, chains, clean_environment, peer, proxy

from solar_forecast import httpx_tls
from solar_forecast.history import (
    InfluxDBGenerationLoader,
    InverterMonitoringLoader,
    PrometheusGenerationLoader,
)
from solar_forecast.weather import OpenMeteoClient

__all__ = ["chains", "clean_environment"]


async def exercise(operation: str, url: str) -> None:
    if operation == "weather":
        client = OpenMeteoClient(base_url=url, timeout=3)
        # Bypass only the retry delay for negative fixtures; the original complete
        # method constructs and performs the real HTTPX request.
        result = await unwrap(OpenMeteoClient.fetch_forecast)(client, 0, 0)
        assert result.latitude == 0 and result.hourly == []
        return
    loader: InverterMonitoringLoader | InfluxDBGenerationLoader | PrometheusGenerationLoader
    if operation == "monitoring":
        loader = InverterMonitoringLoader(base_url=url, api_key="synthetic", timeout=3)
    elif operation == "influx":
        loader = InfluxDBGenerationLoader(url=url, token="synthetic", timeout=3)
    else:
        loader = PrometheusGenerationLoader()
        loader.url, loader.timeout = url, 3
    start = datetime(2026, 1, 1, tzinfo=UTC)
    result = await loader.fetch_generation("test", start, start)
    assert result.records == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["weather", "monitoring", "influx", "prometheus"])
@pytest.mark.parametrize("case", [*CHAIN_CASES, "untrusted", "wrong-host"])
@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
async def test_actual_clients_check_selected_chain(chains, monkeypatch, operation, case, version):
    chain = chains.get(case, chains["strong"])
    calibrate(chain, version)
    ca = chains["strong-ec"][2] if case == "untrusted" else chain[2]
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    body = b'{"latitude":0,"longitude":0,"elevation":0,"timezone":"UTC","hourly":{},"records":[],"status":"success","data":{"result":[]}}'
    if operation == "influx":
        body = b""
    with peer(chain, version, response_body=body) as (port, observed):
        host = "127.0.0.1" if case == "wrong-host" else "localhost"
        url = f"https://{host}:{port}"
        if case.startswith("strong"):
            await exercise(operation, url)
        else:
            with pytest.raises(httpx.ConnectError):
                await exercise(operation, url)
    assert bool(observed["application_bytes"]) == case.startswith("strong")
    if case.startswith("strong") and operation in ("monitoring", "influx"):
        assert b"synthetic" in observed["application_bytes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("encrypted", [False, True])
async def test_normal_proxy_tunnel_keeps_auth_and_verified_origin(chains, monkeypatch, encrypted):
    monkeypatch.setenv("SSL_CERT_FILE", str(chains["strong"][2]))
    # Preserve the proxy's separate certifi selection, only substitute this
    # fixture trust file at the actual certifi API for a private local root.
    monkeypatch.setattr("certifi.where", lambda: str(chains["strong"][2]))
    with (
        peer(chains["strong"], ssl.TLSVersion.TLSv1_3, response_body=b"OK") as (port, observed),
        proxy(port, chains["strong"] if encrypted else None) as (proxy_port, requests),
    ):
        scheme = "https" if encrypted else "http"
        monkeypatch.setenv("HTTPS_PROXY", f"{scheme}://user:password@localhost:{proxy_port}")
        async with httpx_tls.async_client(timeout=3) as client:
            response = await client.get(f"https://localhost:{port}")
            assert response.content == b"OK"
    assert b"Proxy-Authorization: Basic dXNlcjpwYXNzd29yZA==" in requests[0]
    assert b"Proxy-Authorization" not in observed["application_bytes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["weak-2047-root", "weak-root", "untrusted", "wrong-host"])
async def test_proxy_rejects_before_connect_or_credentials(chains, monkeypatch, case):
    chain = chains.get(case, chains["strong"])
    calibrate(chain, ssl.TLSVersion.TLSv1_2)
    ca = chains["strong-ec"][2] if case == "untrusted" else chain[2]
    monkeypatch.setattr("certifi.where", lambda: str(ca))
    with proxy(1, chain) as (port, requests):
        host = "127.0.0.1" if case == "wrong-host" else "localhost"
        monkeypatch.setenv("HTTPS_PROXY", f"https://user:password@{host}:{port}")
        async with httpx_tls.async_client(timeout=3) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("https://localhost:1")
    assert requests == []


@pytest.mark.asyncio
async def test_environment_routing_and_default_limits_match_httpx(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:8081")
    monkeypatch.setenv("HTTP_PROXY", "http://localhost:8082")
    monkeypatch.setenv("ALL_PROXY", "http://localhost:8083")
    monkeypatch.setenv("NO_PROXY", "internal.test,.example.test,localhost:9876")
    async with (
        httpx.AsyncClient(timeout=7) as expected,
        httpx_tls.async_client(timeout=7) as actual,
    ):
        assert actual.timeout == expected.timeout
        assert actual.follow_redirects == expected.follow_redirects
        left = {key.pattern: transport for key, transport in expected._mounts.items()}
        right = {key.pattern: transport for key, transport in actual._mounts.items()}
        assert left.keys() == right.keys()
        for pattern, transport in left.items():
            other = right[pattern]
            if transport is None:
                assert other is None
            else:
                assert other._pool._proxy_url == transport._pool._proxy_url
                assert other._pool._max_connections == transport._pool._max_connections
                assert (
                    other._pool._max_keepalive_connections
                    == transport._pool._max_keepalive_connections
                )
