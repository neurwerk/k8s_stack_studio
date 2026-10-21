# Studio

Studio provides the platform dashboard and its API: user and API-key management, gateway visibility, PII policy tools, notice preferences, usage, and configured MCP connections and setup.

This repository owns the Next.js web app, Python API, database schema, and their images. Base owns deployment charts, routing, and service wiring; Keycloak and the API Key Bridge own identities and keys; PII Engine owns policy evaluation; ContextForge owns personal MCP provider connections.

- [Architecture](architecture/README.md): request flows, permissions, and service boundaries.
- [Development](development/README.md): local environment and quality checks.
- [Operations](operations/README.md): configuration, verification, releases, and recovery ownership.

See the shared [platform architecture](https://github.com/neurwerk/docs/blob/main/dev/architecture/README.md) for the surrounding services.
