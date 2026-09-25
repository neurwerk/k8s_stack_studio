# neurwerk studio agent guidance

Follow `../docs/dev/conventions/coding-and-release.md`: use a dedicated worktree and branch, make the smallest complete change, review the diff, and submit a pull request rather than working on `main`.
Use `design.md` as the direction for UI changes, while checking the current implementation before editing.
Add tests only for meaningful executable logic, security boundaries, or likely regressions; run the repository's required checks before review and use short imperative commit messages such as `fix: clarify log filters`.
For releases, align the API and web versions and lockfiles, validate and merge a reviewed release pull request, then create and push the exact `vX.Y.Z` tag only with separate release authorization; verify the published images before any separately authorized platform adoption or deployment.
Run `./start_dev.sh` for the isolated stack: Studio API and web, PostgreSQL, Keycloak, and the API-key bridge run as real services, while dev simulators return synthetic PII Engine, AgentGateway usage, and OpenSearch responses.
