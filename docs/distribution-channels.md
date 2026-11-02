# Distribution channels

As of 2 November 2026, GitHub stable `v0.1.10` and
[PyPI `0.1.10`](https://pypi.org/project/solar-forecast-langgraph/0.1.10/) are aligned.
[Publication run 41431016677](https://github.com/4alvit/solar-forecast-langgraph/actions/runs/41431016677)
uploaded the existing wheel and sdist after validating the original
`v0.1.10-rc.1` evidence at source commit
`0c542a54d78ec4a9210161a103c211f2d52fe0d8`; it did not rebuild either package.
Both files were downloaded from PyPI and checked against the verified
GitHub release bytes and [PyPI metadata](https://pypi.org/pypi/solar-forecast-langgraph/0.1.10/json):

- `solar_forecast_langgraph-0.1.10-py3-none-any.whl`: 37,101 bytes,
  SHA256 `f198ca06bd979dfc62d6acda562dd89a949888b3a443ef5738c7471f0588511e`.
- `solar_forecast_langgraph-0.1.10.tar.gz`: 71,605 bytes,
  SHA256 `9820b3f5cd758e779d04e82129b72dc81f52afae939deaab9a6697523de48b9e`.

GitHub also contains the source archive and multi-architecture OCI artifact.
PyPI and GHCR retain separate publication steps; a GitHub tag alone does not
prove that either registry contains the same version.

## Install the current stable package

```bash
python -m pip install solar-forecast-langgraph==0.1.10
```

The [README](../README.md#installation) also provides the identical GitHub wheel
as a direct-install alternative. The GitHub release carries `SHA256SUMS` and
`release-manifest.json`. Use an explicit stable version when a deployment
requires the reviewed release bytes.

## Verified container

The same stable release's OCI archive is published as
`ghcr.io/4alvit/solar-forecast-langgraph:0.1.10` for Linux AMD64 and ARM64.
Publication preserved the approved manifest digests and did not rebuild images
or change the floating `latest` tag. Pin the manifest index for installation:

```bash
docker pull ghcr.io/4alvit/solar-forecast-langgraph@sha256:7a6273f87e27ce1264d42a3d08ad04e3c380a603f695440cac37840268439665
```

This records distribution availability; it does not assert deployment or field
forecast accuracy.

## Complete a package promotion

From a reviewed checkout, first run the read-only verifier:

```bash
python3 scripts/publish_verified.py pypi --tag v0.1.10
```

It requires a published stable release, checks the original RC's source policy,
workflow evidence, asset inventory and hashes, and prints the exact upload
commands. If provenance has expired or any check fails, stop and prepare a new
qualified release. Do not rebuild an existing version or bypass verification.

The existing PyPI Trusted Publisher is bound to this repository's `ci.yml`.
For a future promotion, choose an existing stable GitHub release whose version
is not yet published on PyPI. Set `STABLE_TAG` to that exact `vX.Y.Z` tag; do not
republish `v0.1.10`. From the protected `main` branch, a maintainer can publish the
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

For a future unpublished container version, GHCR uses the same separate boundary:

```bash
: "${STABLE_TAG:?Set STABLE_TAG to an unpublished stable container version}"
python3 scripts/publish_verified.py containers --tag "$STABLE_TAG"
```

`--execute` is an explicit publication operation. `--latest` additionally moves
the floating container tag and is not required for a versioned promotion.
Neither operation proves deployment, device acceptance, or forecast accuracy.
