# Security model

## Scope and trust boundaries

Protected assets include source credentials, user/admin identity, raw licensed data, canonical data integrity, model/dataset artifacts, promotion authority, prediction provenance, infrastructure, and audit records.

Trust boundaries:

1. browser to public edge/API;
2. API/worker to PostgreSQL, Redis, object storage, and model registry;
3. ingestion workers to untrusted external content;
4. CI/CD to artifact registry and deployment environment;
5. administrator to privileged governance actions;
6. model artifact load into a code-executing runtime.

External pages, files, headers, datasets, model files, and client payloads are untrusted. Internal network location alone does not make content trusted.

## Threat model

| Threat | Primary controls | Residual/trade-off |
|---|---|---|
| Scraped content exploits parser | Size/type/time limits, raw isolation, no script execution, sandboxed converters, patched parsers, malware scan | Complex PDF/image libraries retain risk; scorecard processing can be separate worker |
| Dataset poisoning/source compromise | Multiple validations, provenance/checksums, volume/distribution drift, source conflict checks, human approval, immutable rollback | A plausible compromised primary source may evade automated tests |
| Temporal leakage/quality manipulation | Point-in-time guards, dataset approval gates, audit, protected branches/artifacts | Insider collusion remains; separation of duties can grow with team |
| Malicious model artifact | Trusted CI build, allow-listed registry, digest/signature, safe format where possible, isolated warm-up | Python ecosystem serialization may require controlled pickle loading |
| API abuse/DoS | Edge and application rate limits, body/query/draw caps, pagination, queue quotas, timeouts, cache, resource isolation | Aggressive limits may inconvenience legitimate analysts |
| Account/token compromise | OIDC/MFA for admins, short tokens, secure cookies, least privilege, revocation, audit | Public endpoints intentionally anonymous |
| SQL injection/data exfiltration | SQLAlchemy parameterization, no user SQL, least-privilege DB roles, response allow-lists | ORM misuse requires review/tests |
| Secret exposure | Secret manager/environment injection, redaction, scanning, rotation, no client secrets | Local developer hygiene remains important |
| Promotion tampering | RBAC, expected-version compare-and-set, approval reason, signed manifest, audit and rollback | Single-person MVP may lack full two-person control |
| Cache confusion | Versioned authorization-aware keys, no secrets/JWTs, cache-control, ETag | More key complexity and lower hit rate |
| Counterfactual misinformation | Synthetic types/labels, strict bounds, no canonical writes, disclaimer | Users may still screenshot out of context |

## Identity, authentication, and authorization

Public catalog and champion analytics are anonymous but rate limited. Administrative operations use a trusted OIDC provider with MFA in staging/production. If a local JWT issuer is used for development, it is never the production default.

JWT policy:

- short-lived asymmetric-signed access token;
- validate issuer, audience, signature algorithm, expiry, not-before, and token ID;
- signing keys rotate through JWKS; never accept algorithm none or symmetric confusion;
- browser session uses Secure, HttpOnly, SameSite cookies at a server boundary where feasible; do not store admin tokens in localStorage;
- revocation/risk policy for privileged actions;
- CSRF protection for cookie-authenticated mutations.

Authorization is deny-by-default with explicit roles in BACKEND_ARCHITECTURE. Model manager and data operator powers are separate. Promotion/rollback and quality overrides require a reason and optimistic version; production should add two-person approval as staffing permits.

## Secret management

- Commit only .env.example with names and safe placeholders.
- Local secrets live in ignored env files or OS secret storage.
- Staging/production secrets come from the platform secret manager/workload identity.
- Prefer short-lived cloud/database credentials over static keys.
- Separate secrets by environment and service; API cannot write raw storage if read-only suffices.
- Rotate database, OIDC, object-store, Sentry, and source credentials; document emergency rotation.
- Logs/config dumps redact authorization, cookies, source tokens, DSNs, object signed URLs, and raw payloads.
- CI uses environment-scoped OIDC federation and protected approvals, not long-lived deploy keys.

## Network and HTTP controls

- TLS at the edge and encrypted managed-service connections; HSTS in public production.
- CORS is an exact environment allow-list of web origins, methods, and headers; never wildcard with credentials.
- Security headers: Content-Security-Policy, frame-ancestors, nosniff, Referrer-Policy, Permissions-Policy, and safe cache-control.
- API/database/Redis/object endpoints remain private where platform supports it.
- Redis requires authentication/TLS in hosted use and is not publicly routable.
- Readiness/admin/metrics endpoints are network restricted or authenticated; liveness discloses only build/status.
- Egress controls are source-specific for ingestion workers where practical.

## Input and output validation

- Pydantic strict schemas reject unknown analytical/admin fields, invalid enums, non-finite numbers, and oversized collections.
- Validate UUIDs, timestamps, cutoff ordering, pagination, simulation count, and counterfactual domains.
- Set edge/server body limits and decompression ratio limits.
- Parameterize all SQL; identifiers/order fields use enum maps rather than user strings.
- Escape UI text through React defaults; sanitize any approved rich content and disallow arbitrary HTML from sources.
- Formula/CSV export cells beginning with dangerous prefixes are escaped.
- Public error messages and source metadata are allow-listed to avoid filesystem, SQL, object URI, and licensed data leaks.

## Scraping and file ingestion

- Document terms/robots/license approval before enabling a source.
- Use a truthful contact user agent where appropriate, per-host concurrency/rate caps, Retry-After, exponential backoff, and bounded backfill schedules.
- Persist raw bytes before parsing and hash them.
- Enforce content length, actual/magic MIME, extension policy, request timeout, redirect/domain limits, and archive expansion limits.
- Disable external entity resolution and network/file access in XML/PDF/image tooling.
- Process risky scorecard documents in a low-privilege, read-only, network-restricted worker with CPU/memory/time limits.
- Quarantine unknown schemas and malware flags; no automatic parser fallback that silently changes meaning.
- Scrub secrets and unnecessary personal data from raw HTTP metadata.

## Dataset and model supply-chain integrity

Dataset:

- manifest lists content hashes, schemas, cutoffs, exclusions, pipeline/container digest, and quality results;
- published alias update is an audited compare-and-set after validation;
- feature code denies target/market namespaces as required;
- suspicious volume, missingness, distribution, identity, and outcome changes block or require review;
- external golden datasets remain comparison-only.

Model:

- build/train in pinned, scanned containers from an approved dataset manifest;
- registry artifact has SHA-256 and preferably a signed/Sigstore provenance statement;
- load only allow-listed registry locations and compatible versions;
- avoid arbitrary pickle where a safe representation works; otherwise trusted build and isolated loading are mandatory;
- golden smoke vectors detect artifact substitution/serialization drift;
- keep rollback versions and referenced artifacts immutable.

Dependencies and containers:

- lock Python/Node dependencies with hashes where supported;
- Dependabot/Renovate updates via review;
- scan SCA, licenses, source, secrets, IaC, containers, and SBOM;
- pin CI actions by immutable commit;
- use minimal non-root runtime images and read-only filesystem where practical.

## Rate limiting and abuse prevention

Use layered limits:

- CDN/WAF/IP burst and sustained limits;
- API principal/IP/token bucket stored in Redis;
- endpoint cost weights: catalog low, prediction medium, counterfactual high, Monte Carlo proportional to draws;
- per-user concurrent-job and daily compute quotas;
- maximum page range, search complexity, simulations, and explanation detail;
- idempotency/request hashing to avoid duplicate work;
- timeouts/circuit breakers for dependencies.

Return 429 with Retry-After. Do not use invasive fingerprinting for the MVP. Rate limits are tuned from load tests and observed abuse, balancing accessibility with cost.

## Audit logging

Append-only audit events cover:

- authentication/role changes and denied privileged attempts;
- source enablement/policy changes and ingestion/backfill triggers;
- identity merges/splits and quality overrides;
- dataset approval/current alias changes;
- model staging/promotion/rollback;
- secret/configuration changes where the platform emits them;
- admin simulation/data exports.

Events carry actor, action, target, request ID, timestamp, safe before/after, reason, and outcome. They exclude tokens and full sensitive/raw payloads. Restrict audit read access, monitor tampering, and retain according to governance policy.

## Privacy and responsible use

Collect minimal user data. Fighters are public professional subjects, but do not infer sensitive personal traits or expose unnecessary private information. Use canonical sporting cohorts only for required evaluation and explain limitations. Provide correction/contact and data deletion workflows where applicable.

Predictions display uncertainty, intended use, and no-betting language. The platform does not optimize for gambling returns, personalized wager recommendations, or vulnerable-user engagement.

## Security verification and incident response

CI/staging gates:

- secret, dependency, license, SAST, IaC, and container scans;
- authz matrix, injection/property, CORS/header, artifact tamper, upload/parser, and rate-limit tests;
- restore and rollback drills.

Incident outline:

1. contain affected credential/source/model/alias;
2. switch to known-good model/dataset or disable capability;
3. preserve logs/manifests and assess exposed predictions;
4. rotate secrets and patch/rebuild from trusted source;
5. notify according to policy;
6. publish corrections/freshness warnings where user-visible;
7. document postmortem and add regression controls.

## Deferred enhancements

Two-person promotion approval, service-mesh mTLS, full artifact signing transparency, dedicated parser sandbox cluster, and external penetration testing are staged as exposure/team grows. They improve defense but cost more than a local-first MVP can initially support; digest verification, RBAC, audit, and isolated workers are non-negotiable now.

