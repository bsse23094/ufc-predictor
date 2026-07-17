# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, credential exposure, raw-data license issue, or model-artifact integrity concern. Report it privately to the repository owner with a minimal reproduction, affected revision, and impact. Until a dedicated reporting channel is configured, use the organization’s established private security contact.

## Supported scope

Only the `main` branch receives security fixes during the foundation phase. Production hosting, authentication, data sources, and model artifacts are not yet deployed or enabled.

## Security commitments

- Secrets stay in ignored local files or the deployment secret manager; `.env.example` contains safe placeholders only.
- Raw data and model artifacts are excluded from Git and are checked in CI.
- Source content, model artifacts, and client input are untrusted by default.
- Production configuration will fail closed for unsafe CORS, missing admin authentication, or untrusted artifact locations.

The authoritative security design and future controls are in [docs/architecture/SECURITY_MODEL.md](docs/architecture/SECURITY_MODEL.md).
