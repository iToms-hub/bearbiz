# Bearbiz Versioning

Bearbiz uses semantic versioning from day one.

## Rules

- Patch: bug fixes and small corrections
- Minor: a meaningful new capability, like a full report or dashboard feature
- Major: breaking changes after the project reaches stability

## Starting point

- `0.0.1` — initial bootstrap
- version bumps happen with each verified milestone

## Publishing a versioned GHCR image

Updating `VERSION` (and the pinned image in `compose.portainer.yml`) does not
publish a semantic-version image tag by itself. The Docker workflow publishes
`latest` and a SHA tag for pushes to `main`; it publishes version tags such as
`1.5.4` only when a matching Git tag such as `v1.5.4` is pushed.

For every production version bump:

1. Set `VERSION` and the production Compose image tag to the same `X.Y.Z`.
2. Merge/push the verified commit to `main` and confirm the `Publish Docker image`
   workflow succeeds for that commit.
3. Create and push the matching GitHub release tag `vX.Y.Z` on that exact commit.
   This triggers the workflow that publishes `ghcr.io/itoms-hub/bearbiz:X.Y.Z`.
4. Confirm the tag exists in GHCR (for example, `docker manifest inspect
   ghcr.io/itoms-hub/bearbiz:X.Y.Z`) before asking Portainer to pull/redeploy it.

Do not assume a version string in the repository or a successful `main` build
means the versioned GHCR image exists. If the image is missing, Portainer can
show a generic HTTP 500 while its logs reveal `manifest unknown` or `not found`.
