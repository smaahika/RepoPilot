# Security Policy

RepoPilot executes repository content and model-proposed edits, so its safety boundaries are part of
the product. The project is pre-release and supports only the latest commit on `main`.

## Report a vulnerability

Please use a [private GitHub security advisory](https://github.com/smaahika/RepoPilot/security/advisories/new)
instead of a public issue. Include the affected version, reproduction steps, impact, and the smallest
safe example you can provide. Do not include live credentials, personal data, or unrelated logs.

Reports will be acknowledged and assessed on a best-effort basis. A fix, disclosure timeline, and
credit will be coordinated through the private advisory before details are published.

## Security expectations

- Treat local verification as trusted-project execution unless the optional Docker backend is used.
- Treat Docker as risk reduction, not a hardened multi-tenant security boundary.
- Review every generated patch before applying it to a source repository.
- Never place API keys in tasks, repositories, generated patches, or issue reports.

The enforced boundaries and residual risks are documented in the
[architecture](docs/architecture.md) and [Docker threat model](docs/docker-sandbox.md).
