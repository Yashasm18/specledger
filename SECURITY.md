# Security Policy

SpecLedger is a UniHack 2026 hackathon prototype, not a production service handling regulated or financial data. This policy is scoped accordingly: it explains what's actually protected today, what isn't, and how to report a problem.

---

## Scope and current posture

There is no formal release/versioning cycle — `main` is the only supported branch, and it's what's deployed at all times. Relevant, real security properties already in place:

- **Write endpoints require authentication.** `POST`/`PATCH` routes under `/catalogue` are gated behind an `X-API-Key` header (`backend/specledger/auth.py`). If `SPECLEDGER_API_KEY` is unset — local dev and CI — the check is a no-op by design; it is always set in production.
- **Rate limiting** on the heaviest, most abusable endpoints (`backend/specledger/rate_limit.py`), auto-disabled under pytest so tests stay fast.
- **Marketplace/reseller domains are hard-blocked** at the source-discovery layer (`BLOCKED_DOMAINS` in `source_discovery.py`) — not a security control per se, but enforced the same way: deny-listed regardless of caller input.
- **No PII, payment, or credential data is processed or stored.** The pipeline handles industrial product catalogue rows (part numbers, descriptions, manufacturer names) only.

Known, disclosed limitation: the frontend's `VITE_API_KEY` is baked into the public JS bundle at build time (GitHub Pages is a static host, so this is unavoidable without a backend-for-frontend proxy this project doesn't have). It deters casual/scripted abuse of write endpoints but is **not a real secret** from anyone who reads the bundle — see [Environment variables](README.md#environment-variables) in the README. Treat it as a rate-limiting speed bump, not an access control boundary.

---

## Reporting a vulnerability

If you find a genuine security issue (auth bypass, injection, data exposure, dependency CVE affecting this codebase):

1. **Do not open a public GitHub issue for it.**
2. Report it privately via [GitHub Security Advisories](https://github.com/Yashasm18/specledger/security/advisories/new) on this repository, or contact the maintainer ([@Yashasm18](https://github.com/Yashasm18)) directly.
3. Include what you found, how to reproduce it, and the affected file/endpoint. A minimal repro is more useful than a general description.

This is a single-maintainer hackathon project, so response time isn't governed by an SLA — but reports will be read and taken seriously, and credited in any resulting fix unless you ask otherwise.
