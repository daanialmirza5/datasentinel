# Security policy

DataSentinel is a portfolio project intended to run locally or behind your own access control; it
has no built-in authentication. See [docs/security.md](docs/security.md) for the threat model and
the defences in place.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's
**Security → Report a vulnerability** (private vulnerability reporting) on this repository, with:

* a description and impact,
* steps or a minimal proof of concept (synthetic data only),
* the affected version (`GET /api/v1/health`).

Only the latest version on the default branch is supported. No bounty is offered.
