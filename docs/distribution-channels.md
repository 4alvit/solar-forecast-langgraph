# Distribution channels

As of 12 October 2026, GitHub stable `v0.1.4` and
[PyPI `0.1.4`](https://pypi.org/project/solar-forecast-langgraph/0.1.4/) are aligned.
[Publication run 38299579517](https://github.com/4alvit/solar-forecast-langgraph/actions/runs/38299579517)
uploaded the existing wheel and sdist after validating the original
`v0.1.4-rc.1` evidence at source commit
`fee15148e0d6fcf7a4b4dbd1ece6a2ff895bc990`; it did not rebuild either package.
Both files were then downloaded from PyPI and checked against the verified
GitHub release bytes and [PyPI metadata](https://pypi.org/pypi/solar-forecast-langgraph/0.1.4/json):

- `solar_forecast_langgraph-0.1.4-py3-none-any.whl`: 29,424 bytes,
  SHA256 `d6ece9d36cd3a78535cc73b9eb142e742f823c4264df20984323382a42cd4ca9`.
- `solar_forecast_langgraph-0.1.4.tar.gz`: 50,702 bytes,
  SHA256 `65445689f693a03649404166fd7b119d96d24cf2acb7782a55836ac4872fa814`.

GitHub also contains the source archive and multi-architecture OCI artifact.
PyPI and GHCR retain separate publication steps; a GitHub tag alone does not
prove that either registry contains the same version.

## Install the current stable package

```bash
python -m pip install solar-forecast-langgraph==0.1.4
```

The [README](../README.md#installation) also provides the identical GitHub wheel
as a direct-install alternative. The GitHub release carries `SHA256SUMS` and
`release-manifest.json`. Use an explicit stable version when a deployment
requires the reviewed release bytes.

## Complete a package promotion

From a reviewed checkout, first run the read-only verifier:

```bash
python3 scripts/publish_verified.py pypi --tag v0.1.4
```

It requires a published stable release, checks the original RC's source policy,
workflow evidence, asset inventory and hashes, and prints the exact upload
commands. If provenance has expired or any check fails, stop and prepare a new
qualified release. Do not rebuild an existing version or bypass verification.

The existing PyPI Trusted Publisher is bound to this repository's `ci.yml`.
For a future promotion, choose an existing stable GitHub release whose version
is not yet published on PyPI. Set `STABLE_TAG` to that exact `vX.Y.Z` tag; do not
republish `v0.1.4`. From the protected `main` branch, a maintainer can publish the
verified release without a long-lived PyPI token:

```bash
: "${STABLE_TAG:?Set STABLE_TAG to the next unpublished stable vX.Y.Z tag}"
python3 scripts/publish_verified.py pypi --tag "$STABLE_TAG"
gh workflow run ci.yml --repo 4alvit/solar-forecast-langgraph --ref main -f stable_tag="$STABLE_TAG"
```

The first job has read-only GitHub access and no OIDC permission. It runs the
same immutable-evidence verifier, checks the distribution metadata, and stages
only the original wheel and sdist. A separate publishing job verifies the
transferred file inventory and hashes against the first job's receipt digest,
then uses the official PyPA action with job-scoped OIDC access. Neither job
builds a package. `ci-checks.yml` retains the reusable application checks;
publication cannot run through the pull-request or release validation paths.

Publication fails on existing filenames. If an upload stops part-way through,
inspect PyPI's existing file hashes before choosing a recovery action; do not
blindly skip duplicates. After each promotion, verify that version and both
distribution hashes in PyPI's version-specific JSON metadata against the GitHub
manifest before recommending the new pinned install command.

The local `--execute` option remains available to operators with separately
configured credentials, but the workflow uses the existing OIDC trust.

GHCR uses the same separate boundary:

```bash
python3 scripts/publish_verified.py containers --tag v0.1.4
```

`--execute` is an explicit publication operation. `--latest` additionally moves
the floating container tag and is not required for a versioned promotion.
Neither operation proves deployment, device acceptance, or forecast accuracy.
