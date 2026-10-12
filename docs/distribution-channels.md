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

After the operator approves publication and configures PyPI credentials for this
project, repeat with `--execute`. This uploads the existing approved wheel/sdist;
it does not build a new package. Verify the version and both distribution hashes
at `https://pypi.org/pypi/solar-forecast-langgraph/0.1.4/json` against the GitHub
manifest before recommending the PyPI install command again. Never overwrite a
published version.

GHCR uses the same separate boundary:

```bash
python3 scripts/publish_verified.py containers --tag v0.1.4
```

`--execute` is an explicit publication operation. `--latest` additionally moves
the floating container tag and is not required for a versioned promotion.
Neither operation proves deployment, device acceptance, or forecast accuracy.
