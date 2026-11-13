# Release management

HoundBrowser follows semantic versioning. During 0.x, APIs may change between minor versions; callers should pin exact versions.

1. Update the version in `pyproject.toml` and `src/houndbrowser/__init__.py`, the changelog, and examples if behavior changed.
2. Run Python/JavaScript tests, dependency and secret audits, documentation/link checks, and a container smoke test. Inspect the built wheel and source archive for unexpected files.
3. Merge the reviewed commit to main. Create a `vX.Y.Z` tag only after checks pass.
4. Publish a GitHub release with the source distribution, wheel, SHA256SUMS, and release notes. The release workflow rebuilds and verifies artifacts from the tagged source before uploading them.
5. Verify tag, release assets, repository visibility, license recognition, and the open-source hub's GitHub release feed.

Package-registry publication is a separate action. A GitHub release does not mean the package exists on PyPI or npm. Use signed/provenance-attested builds when your publishing platform supports them; never claim an attestation that was not produced.
