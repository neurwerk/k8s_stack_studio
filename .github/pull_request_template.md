## Summary

Describe the user-visible change and its motivation.

## Issues

Closes #<!-- implementation issue -->

Parent: #<!-- link only; do not use Closes/Fixes/Resolves -->

## Affected Contracts

List affected API, web, authorization, PII, logging, image, chart, and consuming-repository contracts, or state `None`.

## Validation

- [ ] API: `uv run ruff check .`
- [ ] API: `uv run ruff format --check .`
- [ ] API: `uv run ty check`
- [ ] API: `uv run pytest`
- [ ] Web: `pnpm lint`
- [ ] Web: `pnpm typecheck`
- [ ] Web: `pnpm test`
- [ ] Web: `pnpm build`
- [ ] Not applicable checks are explained below.

Record exact command results:

## Release Checklist

- [ ] API and Web declared versions remain aligned.
- [ ] API and pnpm lockfiles match their manifests.
- [ ] A release tag is not required, or the exact `vX.Y.Z` release impact is described.
- [ ] Documentation and deployment contracts are updated when applicable.
- [ ] No credentials, tokens, personal data, or generated local files are included.

Image publication is tag-driven. Opening or merging this pull request must not publish images.

## Release Classification

Apply exactly one: `release: none`, `release: notes`, `release: platform`, or `release: client`.
