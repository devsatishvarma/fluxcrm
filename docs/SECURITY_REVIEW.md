# GlideCRM security review

Date: 2026-11-23  
Scope: authentication, MFA, password reset, Graph mail, logging, deployment config, and related uncommitted hardenings.

## Verdict

No critical remote code-execution or auth-bypass bugs found in the current code path. Several medium issues around reset-link host trust, MFA brute-force, log leakage of reset tokens, and console-backend reset mail were present; those are hardened in this pass. Remaining risk is mostly **operational** (Azure app secret, host access, TLS/HSTS settings on the VPN host).

## Findings addressed in this pass

| Severity | Issue | Mitigation |
| --- | --- | --- |
| High | MFA verify lacked application-level throttle (django-otp alone) | `mfa_verify` uses `is_throttled` / `record_attempt` (5 failures / 15 minutes) |
| High | Password-reset email links could follow a forged `Host` header | `GlidePasswordResetForm` pins domain/protocol to `PUBLIC_BASE_URL` |
| Medium | On-screen reset URL used `build_absolute_uri` only | Prefer `PUBLIC_BASE_URL`; fallback only when unset |
| Medium | Self-serve reset could print tokens via console email backend | Startup `ImproperlyConfigured` when `PASSWORD_RESET_ENABLED` + console backend without Graph |
| Medium | Gunicorn access logs could contain reset token paths | `glidecrm.gunicorn_logging.RedactingLogger` in Compose and Dockerfile CMD |
| Low | On-screen reset page could be cached by browsers/proxies | `Cache-Control: no-store` on link page and confirm view |
| Low | Ops guidance thin for Graph secret / break-glass MFA | `docs/DEPLOYMENT.md` security notes section |

## Remaining / accepted risks

| Severity | Issue | Owner action |
| --- | --- | --- |
| High (ops) | `AZURE_CLIENT_SECRET` grants `Mail.Send` as the shared mailbox outside the app | Store only in host secrets; rotate; restrict Entra app permissions; monitor Graph sign-ins |
| Medium (ops) | Anyone with Docker/SSH on the host can run `clear_mfa` and read env secrets | Lock down SSH, Compose access, and who can `docker compose exec` |
| Medium (ops) | VPN-only deploy still needs correct `ALLOWED_HOSTS`, CSRF origins, TLS, and HSTS | Follow `docs/DEPLOYMENT.md`; run `manage.py check --deploy` before go-live |
| Low | On-screen reset still falls back to request host if `PUBLIC_BASE_URL` / `SITE_ADDRESS` unset | Always set `PUBLIC_BASE_URL` on real hosts |
| Low | Media uploads are local filesystem; logo type/size limited but not a full AV pipeline | Keep uploads off public internet; review disk quotas |
| Info | MFA can be disabled with `DJANGO_MFA_REQUIRED=false` | Break-glass only; re-enable immediately |

## What looks solid

- No public self-registration; first-run setup is one-shot.
- Session auth + CSRF; secure cookies / HSTS knobs for production.
- Login and password-reset throttling with hashed subjects.
- Password reset tokens single-use and time-limited (`PASSWORD_RESET_TIMEOUT`).
- Audit events avoid logging tokens/passwords; structured logs redact sensitive paths where middleware applies.
- Graph mail refuses to send CRM deep links without `PUBLIC_BASE_URL`.
- Role checks gate user admin, on-screen reset, and MFA clear to Super Admin.

## Recommended go-live checklist

1. `DJANGO_DEBUG=false`, unique `DJANGO_SECRET_KEY`, tight `DJANGO_ALLOWED_HOSTS` / CSRF origins.
2. `DJANGO_MFA_REQUIRED=true` (default); enroll every account.
3. Graph vars + `PUBLIC_BASE_URL` set **before** `DJANGO_PASSWORD_RESET_ENABLED=true`.
4. `DJANGO_SECURE_COOKIES=true` and TLS (or trusted reverse proxy + `DJANGO_TRUST_PROXY_HEADERS`).
5. Confirm Gunicorn starts with `RedactingLogger` (Compose command or image CMD).
6. Restrict host shell access; document who may run `clear_mfa`.
7. Rotate Azure client secret on a schedule; never commit `.env`.

## Retest coverage added

- MFA application throttle returns 429 after five failed verifies.
- Emailed reset link uses `PUBLIC_BASE_URL` even when `Host` is hostile.
- On-screen reset link uses `PUBLIC_BASE_URL` and sends `Cache-Control: no-store`.
