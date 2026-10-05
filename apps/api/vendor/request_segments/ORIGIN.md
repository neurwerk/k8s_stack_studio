# Request segments source

Canonical source: `neurwerk/k8s_stack_agentgateway_extproc`,
`packages/request_segments`.

This snapshot is from the coordinated segment-contract change based on
`09615de90b44fb13ed71891d2b26a8c0f5cf027f` (the new package is not yet published).
It is vendored so Studio builds independently without an unpublished registry
dependency. Only Python and Pydantic are required.

Package version: `0.1.0`. This finalized snapshot includes `pyproject.toml`,
`README.md`, `LICENSE`, and `src/**/*.py` only; caches and build output are excluded.
Source SHA-256: `2a7006a9c37f73b4f0f96d7b973dee8ea132c880da1d0fe81d85680b61377a89`.
The digest covers files sorted by relative POSIX path, feeding each UTF-8 path,
a NUL byte, its exact file bytes, then a NUL byte into SHA-256. `ORIGIN.md` is
consumer provenance and is not part of the source digest.

Make changes in the canonical package, then copy its source and package metadata
here together. Do not maintain a separate Studio implementation.
