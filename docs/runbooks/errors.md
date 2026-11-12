# Runbook: error tracking (Sentry)

Spec 015 §1. The API and the browser report unhandled errors to Sentry with **no personal data**:
stack traces, the request id, and the ids `user.id`, `org_id`, `role` (+ `is_admin` on the API).
Never names, usernames, emails, answers, code, tutor text, request bodies, query strings,
cookies or auth headers. The code enforces this (`backend/app/core/observability.py`,
`frontend/src/lib/observability.ts`); the project settings below are a second layer.

Sentry is **off** unless a DSN is set. Tests never set one.

## 1. Create the project (once)
1. Sign up for Sentry SaaS, **free plan**, and choose the **EU (Frankfurt) data region** when
   creating the organisation (it can't be changed later).
2. Create two projects: `learning-api` (platform: Python / FastAPI) and `learning-web`
   (platform: React). Two projects keep the quotas and alert rules apart.
3. In **each** project → Settings → Security & Privacy:
   - **Data Scrubber**: on. **Use Default Scrubbers**: on.
   - **Prevent Storing of IP Addresses**: on.
   - **Scrub IP Addresses**: on (if shown).
   - Additional sensitive fields: `display_name`, `username`, `response`, `code`, `text`,
     `display_names`.
4. Alerts → Create alert → "Issues": **When a new issue is first seen → send an email** to the
   developer on call. Nothing else (no performance alerts: tracing is off).

## 2. Configure the app
| Where | Variable | Value |
|---|---|---|
| API host env | `SENTRY_DSN` | `learning-api` DSN |
| API host env | `GIT_SHA` | the deployed commit (optional; becomes the Sentry release) |
| SPA build env | `VITE_SENTRY_DSN` | `learning-web` DSN (public by design; it's in the bundle) |

`ENVIRONMENT` (`production`, `development`, `test`) becomes the Sentry environment on the API;
the SPA uses the Vite mode. The SPA's CSP `connect-src` is built from `VITE_SENTRY_DSN`, so rebuild
after changing it.

## 3. Using it
- A student or teacher reads out **"Error code: ab12cd34"** (screen) or **"(code ab12cd34)"**
  (toast). That's the first 8 characters of the API request id or the Sentry event id. In Sentry,
  search `request_id:ab12cd34*` (API) or open the event id (browser).
- The API also logs every 500 with the request id (`request_id` field in the JSON log line in
  production).
- `ApiProblem` 5xx (502/503 when Supabase or DeepSeek is down) are grouped **one issue per code**
  (fingerprint `api-problem`, `<code>`). 4xx are never reported.
- A Pyodide load failure (school network blocks jsDelivr, very old browser) is one event per page
  session with fingerprint `pyodide-load-error`. Errors in students' own code are never reported.
- Smoke test in development: `GET /api/v1/debug/boom` (signed in; the route exists only when
  `ENVIRONMENT=development`).

## 4. Free quota (5k errors / month)
Sentry drops events past the quota until the month resets; the app is unaffected.
When the usage email arrives:
1. Look at the top issues: one noisy issue (a loop, a browser extension, a bot) is the usual cause.
2. Fix it, or in Sentry **Discard and delete** future events of that issue, or add an inbound
   filter (Settings → Inbound Filters: legacy browsers, web crawlers, localhost).
3. If real errors exceed the quota, that's an incident: fix the cause rather than buying quota.

## 5. Legal review note
Sentry is a third data flow (with Supabase and DeepSeek): ids and stack traces only, stored in the
EU. It's listed in docs/PRD.md Constraints for the legal review.
