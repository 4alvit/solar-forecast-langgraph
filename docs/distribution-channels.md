# Distribution channels

As of 12 October 2026, GitHub stable `v0.1.4` contains the approved wheel, sdist,
source archive and multi-architecture OCI artifact. PyPI's latest distribution
is `0.1.2`. The two channels have independent publication steps; a GitHub tag is
not evidence that PyPI or GHCR contains the same version.

## Install the current stable package

Use the explicit wheel URL in the [README](../README.md#installation). The release
also carries `SHA256SUMS` and `release-manifest.json`. Do not substitute a moving
`main` checkout when a deployment requires the reviewed release bytes.

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
From the protected `main` branch, a maintainer can publish the verified release
without a long-lived PyPI token:

```bash
gh workflow run ci.yml --repo 4alvit/solar-forecast-langgraph --ref main -f stable_tag=v0.1.4
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
blindly skip duplicates. Verify the version and both distribution hashes at
`https://pypi.org/pypi/solar-forecast-langgraph/0.1.4/json` against the GitHub
manifest before recommending the PyPI install command again.

The local `--execute` option remains available to operators with separately
configured credentials, but the workflow uses the existing OIDC trust.

GHCR uses the same separate boundary:

```bash
python3 scripts/publish_verified.py containers --tag v0.1.4
```

`--execute` is an explicit publication operation. `--latest` additionally moves
the floating container tag and is not required for a versioned promotion.
Neither operation proves deployment, device acceptance, or forecast accuracy.
