# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.5.x   | ✅ Security fixes   |
| 0.4.x   | ✅ Security fixes   |
| < 0.4   | ❌ End of life      |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Send details to the maintainers via private channel. Include:

- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact
- Suggested fix (if any)

We aim to acknowledge within 48 hours and publish a fix within 7 days.

## Security Model

### Trust Boundaries

```
User/Agent ──── API Key ──→ Emerald API (FastAPI)
                                │
                   ┌────────────┼────────────┐
                   ▼            ▼            ▼
              PostgreSQL     Neo4j         Redis
              (memory data)  (graph)       (cache/sessions/locks)
                   │
                   ▼
              MinIO (S3)
              (file storage)
```

1. **API Key** is the primary authentication mechanism. Every request must include a valid key.
2. **Entity isolation** — API keys are scoped to specific entities. Cross-entity access is blocked by `authorize_entity()`.
3. **Data at rest** — All database connections use encrypted credentials from environment variables.
4. **Data in transit** — Production deployments should use TLS for all service connections.

### Key Security Measures

| Measure | Status |
|---------|--------|
| API Key authentication | ✅ Enforced on all routes |
| Entity-level authorization | ✅ `authorize_entity()` on all data routes |
| CORS production restrictions | ✅ No wildcard in production |
| OAuth state in Redis (multi-worker safe) | ✅ TTL 10 min |
| Encryption key separation | ✅ `encryption_key` independent from `api_key_secret` |
| Session JWT with dedicated secret | ✅ `session_jwt_secret` configurable |
| Rate limiting (sliding window) | ✅ Per-endpoint limits |
| Dependency vulnerability scanning | ✅ CI workflow (`security.yml`) |
| Secret detection (Gitleaks) | ✅ CI workflow + `.gitleaks.toml` |

### What We Don't Protect Against (Out of Scope)

- Physical server access — deploy Emerald in a trusted environment
- Compromised API keys — keys are bearer tokens; rotate if leaked
- Malicious admin users — Emerald trusts operators with database access
- Network-level MITM — use TLS in production

## Dependency Policy

- Dependencies are pinned with minimum versions in `requirements.txt` / `pyproject.toml`
- CI runs `pip-audit` weekly and on every PR
- Critical CVEs are patched within 7 days
- Extraction dependencies (PyMuPDF, faster-whisper, etc.) are optional and loaded lazily

## Development Practices

1. **No secrets in code** — All credentials come from environment variables
2. **`.env` never committed** — `.gitignore` blocks all `.env` files except `.env.example` and `.env.test`
3. **CodeQL static analysis** — runs on every push/PR via GitHub Actions
4. **Pre-commit hooks** — Gitleaks secret detection before commit

## Vulnerability Disclosure Process

1. Reporter sends details privately
2. Maintainers acknowledge within 48 hours
3. Fix developed and tested
4. Patch released with security advisory
5. CVE requested if applicable
6. Public disclosure after patch is available
