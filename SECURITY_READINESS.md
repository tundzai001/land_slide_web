# Security and quality readiness

Status date: 2026-10-10. Scope: application changes in this repository. This is engineering evidence, not ISO 27001 or ISO 9001 certification, an audit opinion, or verification of the deployed service.

## Implemented controls

- Browser login uses an HttpOnly, Secure, SameSite=Lax session cookie in production. The signed credential is not returned to browser JavaScript or saved in browser storage. Unsafe cookie-authenticated requests require an allowed Origin and a session-bound CSRF header. API clients can continue to use explicit bearer tokens. Browser cookie credentials cannot be replayed as bearer tokens.
- Old browser bearer tokens are removed from local/session storage on the next page load. Users must sign in again after this release. Cookie signing depends on `SECRET_KEY`: rotating that key ends all existing sessions.
- Login attempts are throttled per source IP and account in shared PostgreSQL storage. Unknown and disabled accounts receive a uniform login failure. New/reset passwords require at least 12 characters and respect bcrypt's 72-byte UTF-8 limit.
- Access JWTs require an expiry, issue time, subject, unique session ID and purpose. Sessions are stored in the operations database, enforce idle and absolute expiry, and are invalidated by logout or password change. Users can inspect their active sessions and revoke one or all other sessions. Authentication fails closed if session storage is unavailable.
- WebSocket tickets expire quickly, are consumed once, and are bound to a live parent session and authorization scope. Connected sockets recheck the session and project/role scope, and same-worker sockets close promptly after session revocation. Restricted users receive no project data outside their assignment.
- Project and station queries default to authenticated access. Public aggregate dashboard data remains a separate route. User and rescue inputs are bounded and validated; user edits preserve assignments if project loading fails. Validation failures omit submitted values, and 5xx API responses omit internal exception details.
- Production startup rejects a default/short signing key, wildcard CORS, unsupported JWT algorithm, invalid token lifetime and the sample MQTT password. API responses are not cached; browser security headers and request IDs are emitted. HTTPS responses include HSTS.
- The map now provides chart inspection, filtering, export, refresh feedback and accessible tabular values. Management user forms report errors without wiping edits or submitting duplicates.

## Verification

The focused backend tests cover cookie/CSRF/bearer compatibility, session revocation and expiry, WebSocket access, user/rescue validation and error redaction. Browser tests cover login routing, user forms, basemap switching and chart interactions at desktop and narrow widths. Run with disposable databases and controlled configuration; never point tests at production data.

```sh
PYTHONPATH=backend python -m pytest -q backend/tests/test_auth_jwt.py backend/tests/test_security_controls.py backend/tests/test_browser_sessions.py backend/tests/test_error_responses.py backend/tests/test_websocket_manager.py backend/tests/test_websocket_authorization.py backend/tests/test_user_input_controls.py backend/tests/test_rescue_input_controls.py
npm run build:frontend
npx playwright test tests/ui/auth-session.spec.js tests/ui/user-security-workspace.spec.js tests/ui/map-workspace-tools.spec.js --project=chromium
```

Store CI results, dependency scan output, review approvals, deployment configuration checks, backup restore tests and penetration-test reports with the release record. Re-run verification after authentication or dependency changes.

## Production rollout

Provision a random `SECRET_KEY` of at least 32 bytes, unique `MQTT_PASSWORD`, exact `CORS_ORIGINS` and `PUBLIC_SITE_URL`, TLS at the edge, protected backups, least-privilege database accounts and monitoring. Serve the public site and API from the configured origins. Set `PUBLIC_MONITORING_ENABLED=true` only after classifying the underlying project/station data for public release. Rotate credentials previously exposed in source history. Validate proxy, HTTPS, HSTS, cookie delivery, logout, WebSocket revocation and CSRF behavior in the deployed environment.

For the Windows `python server.py` deployment, run `python -c "import secrets; print(secrets.token_urlsafe(48))"` once and copy the output into `C:\inetpub\wwwroot\land_slide_web\backend\.env` as `SECRET_KEY=<generated value>`. Keep this value private and stable across restarts and application instances; replacing it ends existing sessions. Set `MQTT_PASSWORD` to the actual non-sample broker credential as well. The `.env` file is ignored by Git. Do not use `ENVIRONMENT=development` to bypass production checks.

The browser migration requires a coordinated frontend/backend rollout. Deploy the backend first, then the frontend assets; cached older browser code may require a reload and users will sign in again. Existing explicit bearer API clients continue to work. Keep the previous deployment and database backup available for rollback; no schema migration is required by these controls.

## ISO 27001 / ISO 9001 evidence still required

Assign owners and maintain the risk assessment, access policy, asset and data inventory, retention schedule, incident-response records, supplier reviews, backup restore evidence, change approvals, training, internal audit, management review, corrective actions and service-quality measures. Map applicable controls to the editions and audit scope chosen with the certification body. A code repository alone cannot establish these organization-wide controls.

## Remaining material gaps

- Multi-factor authentication, centralized identity and privileged-action step-up are absent.
- The current CSP allows scripts required by legacy inline handlers and external libraries. Remove inline handlers and tighten CSP in a separate compatibility-tested change.
- Rate limits use the resolved peer address. Configure trusted proxies at the edge; do not trust arbitrary forwarded-IP headers.
- Cross-instance WebSocket revocation becomes effective on the periodic recheck (up to 30 seconds); same-worker connections close immediately. A shared pub/sub revocation channel would shorten this delay.
- Deployment settings, current dependencies, TLS configuration and operational controls have not been independently audited here. Do not claim ISO conformity or production security from these code tests.
