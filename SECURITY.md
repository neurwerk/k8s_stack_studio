# Security Policy

## Supported Versions

Security fixes are applied to the latest released version. Older versions may
not receive security updates.

## Reporting A Vulnerability

Do not open a public issue for a suspected vulnerability. Report it privately
through the repository's GitHub Security Advisory form:

https://github.com/neurwerk/k8s_stack_studio/security/advisories/new

If private vulnerability reporting is unavailable, contact `dev@neurwerk.com`.
Include the affected version, impact, reproduction steps, and any suggested
mitigation. Do not include live credentials, private keys, access tokens,
personal data, or customer configuration.

We will acknowledge the report, investigate it, and coordinate remediation and
disclosure with the reporter. Please allow time for a fix before publishing
details.

## Security Expectations

- Keep all non-example environment files out of version control.
- Supply confidential runtime values through a secret manager or equivalent
  deployment mechanism.
- Use trusted CA certificates for remote TLS endpoints.
- Restrict insecure PII Engine and OpenSearch options to disposable, exact
  loopback-only local development.
- Never expose the unauthenticated management port outside its trusted network.
