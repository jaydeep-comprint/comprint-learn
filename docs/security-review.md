# Security review

Spec 015 §5. **Reviewed 2026-11-12** on `feat/015-operations-3` (stacked on PR 2): the whole
codebase, not only spec 015's diff. Repeat it, and re-date this file, before the pilot if more than
a month has passed (a line in `docs/pilot-readiness.md`).

**Result: PASS.** No critical or high finding is open. The one high (area 5) and all mediums except
the ones listed under "Open" were fixed in this spec.

**Method.** The `security-reviewer` subagent ran once per area, on whole paths with the area's
checklist line, read-only; each run's findings were triaged here. Severity: critical / high /
medium / low. Evidence is a test name, `file:line` or a command's output.

## Summary

| # | Area | Result | Fixed in 015 | Open (owner) |
|---|---|---|---|---|
| 1 | Authentication | PASS | 2 low | 3 low (user) |
| 2 | Tenant isolation | PASS | 1 low (structural test) | 3 low/info |
| 3 | Authorisation | PASS | 1 low | 1 low (deploy) |
| 4 | Answer-key leakage | PASS | 1 medium | 2 low (accepted) |
| 5 | Input handling | PASS | **1 high**, 1 low | 3 low |
| 6 | AI | PASS | 2 medium; evals run and recorded | 1 low |
| 7 | Privacy endpoints (spec 014) | PASS | 1 low | 2 info |
| 8 | Secrets | PASS | 1 low | 2 low (accepted) |
| 9 | Data at rest and in transit | PASS | 2 medium, 3 low | 1 (user: Supabase CA in production) |
| 10 | Headers, CORS, rate limits, body cap, errors | PASS | 2 low | 2 low |
| 11 | Dependencies | PASS | 1 medium, 3 low | 1 low |
| 12 | Client | PASS | 2 low | — |

## 1. Authentication — PASS
Evidence:
- Algorithm confusion blocked: HS256 only with the legacy secret, else ES256/RS256/EdDSA with the
  key's own algorithm (`app/core/auth.py`; `test_hs256_token_rejected_without_legacy_secret`,
  `test_bad_signature_rejected`).
- `exp`, `iat`, `sub`, `aud`, `iss` required, 30 s leeway (`test_bad_claims_rejected`,
  `test_expired_token_rejected_with_leeway`); anon/service-role keys rejected (no `sub`).
- Unknown `kid` refetches at most once per 30 s under a lock; stale keys kept on failure
  (`test_unknown_kid_refetches_once_then_rejects`, `test_jwks_unreachable_uses_stale_cache`).
- Role and school come from the `app_user` row only (`deps.py`).
- `sessions_valid_after` set on admin reset, in-app password change and deactivation
  (`test_tokens_issued_before_sessions_valid_after_are_rejected`); deactivated/erased → 401 and
  banned in Supabase.
- Temp-password gate: only `GET /me`, `POST /me/password` let it through
  (`test_only_allowlisted_routes_skip_password_change_check`,
  `test_must_change_password_blocks_normal_routes_only`).
- Per-user rate limit before the DB lookup; per-IP limit only for missing/invalid tokens.
- Invite redirect built from `APP_URL` (https enforced in production); login `from` comes from
  router state only.
- Temp passwords from `secrets` (~22.7 bits), held in memory only on the client; synthetic student
  emails are never emailed (`create_user` with `email_confirm`).
- Supabase dev project: public sign-up **off**, Site URL and redirect allow-list set to the app
  (confirmed by the user, 2026-11-12).

Fixed: a student's synthetic email was shown on `/reset-password` (`authErrors.shownEmail`); JWKS
cold start with the key endpoint down now fails fast for 5 s instead of queueing every request
(`test_cold_start_with_jwks_down_fails_fast_then_retries`).

Open (owner: user):
- **L1** Reactivating a user may revive refresh tokens issued before deactivation if Supabase's ban
  doesn't revoke them. Confirm against Supabase (sign in, deactivate, reactivate, try the old
  refresh token); fix = set a random password on deactivation.
- **L2** `POST /me/password` needs no current password, so a stolen session can become a takeover.
  Fix = allow it only while `must_change_password` (a product decision).
- **L4** `TRUSTED_PROXY_COUNT` must match the deployment (deploy checklist).
- By design: a staff email-recovery reset doesn't set `sessions_valid_after`; temp passwords don't
  expire; any teacher can reset any student's password (audited).

## 2. Tenant isolation — PASS
Evidence: `OrgScope` adds `org_id` to every query and 404s other schools' ids (`deps.py`); the
route walker (`test_routes_with_tenant_ids_use_org_scope`, `test_every_route_authenticates`); an
AST scan of every tenant query (6 statements without an org filter, each justified: correlated
`exists`, operator-only jobs, an insert helper, the global email check); bulk id lists scoped
(`assignments._check_students`, enrolment, consent, `class_view.load`); upserts keyed on the
caller or scoped rows; composite foreign keys everywhere (`test_db_rejects_cross_school_links`);
cross-school 404 tests (`test_every_endpoint_404s_on_other_school_ids` and feature tests).

Fixed: `tests/test_tenant_fks.py` now fails if any link between two tenant tables lacks `org_id`.

Open: five upserts without an `org_id` where-guard (defence in depth only); the isolation snapshot
covers a subset of tables (feature tests cover the rest); an invite reveals that an email exists on
the platform (Supabase emails are global; admins only).

## 3. Authorisation — PASS
Evidence: `scripts/route_roles.py` (88 routes: role required and `OrgScope` per route; only health,
`/me`, `/me/password` and the two global content routes skip `OrgScope`). Admin-only routes use
`AdminScope`; student status changes are admin-only
(`test_deactivate_student_admin_only_and_signs_out`); per-student class routes check enrolment;
student-owned rows re-check the owner (`quiz._own`, `placement._own`, `kp_flow._remediation`,
reviews, XP, tutor); staff previews write nothing; students never get other students' ids on the
leaderboard.

Fixed: `tenancy.patch_student` re-checks admin for status changes (not only the route).

Open: with `ENVIRONMENT` unset the app is in development (debug route, `/docs`): must be set
(deploy checklist). By design: any teacher manages any class of the school (spec 014).

## 4. Answer-key leakage — PASS
Evidence: `split_item` puts keys only in `answer`; `ItemPublic` forbids extra fields
(`test_content_split`); questions are built from `public`, hidden tests' expected values never
leave the server; seeds are server-side (`secrets`), graded with the session's seed; MCQ
positional ids with a per-student shuffle; quiz and placement answers return no correctness until
the end; the tutor's context has no answers before answering and every reply passes the guard;
the dashboard and export read keys server-side only; the content-assets plugin serves images
only; a grep of `dist/` finds no answers.

Fixed (**medium**): a retry could re-serve a fixed question whose answer (or a KP code item's
solution) was shown in the failed session. `choose_next_item` now prefers unanswered items, then
answered param items (new numbers), then answered fixed items
(`test_retry_prefers_new_numbers_over_a_fixed_item_whose_answer_was_shown`).

Open (accepted): per-test verdicts on hidden code tests let a student hand-craft outputs over
several tries (decision 6; server-side execution is v2); the tutor confirming a draft answer is
stopped by the prompt only (the eval probes are the gate).

## 5. Input handling — PASS
Evidence: student maths goes through the AST whitelist walker, never `parse_expr`/`sympify`
(`test_grading.py`, `test_content_params.py`); `simplify` runs in a 1 s pool; numeric and unit
parsing are strict regexes; Markdown has no raw HTML, `javascript:` URLs dropped, images only from
content paths, KaTeX `trust` off, Mermaid `strict`; SQL only through binds, `ILIKE` escapes `%`,
`_`, `\`; no upload surface; length limits on every free-text field.

Fixed (**high**): a short answer such as `sqrt(999…9^100+1)` made SymPy factor a huge integer
while parsing (`factorint`, holding the GIL), stalling the whole API for seconds to minutes. Roots
of exact numbers over 256 bits are now refused while parsing (`params._check_root`;
`test_roots_of_huge_numbers_are_refused_fast`, all < 0.1 s).

Open: the `response` schema allows 10 000 chars while the quick-answer path enforces 200 (no path
uses the gap); model-written links in tutor replies are clickable (`rel="noopener noreferrer"`);
two schemas are wider than the service limits (enforced later).

## 6. AI — PASS
Evidence: the tutor's context has no names or ids; student text is scrubbed before sending and
storing; teacher summaries send pseudonyms only (`test_render_carries_no_ids_or_names`); student
text and facts are delimited and escaped; the answer guard runs on every reply
(`test_tutor_guard`, `test_tutor_rules`) and the citation guard on every summary; JSON output is
parsed strictly; caps run under advisory locks (3 hints / 10 chats per thread, 20 a day; summaries
10 per teacher, 50 per school); the consent gate in Tx 1 and Tx 2 (`test_tutor_api_db`,
`test_consent_db`); no prompt or reply is logged; tutor text is purged after 180 days.

Fixed (**medium**): the phone scrubber now catches `98765 43210`, `98765-43210`,
`+91 98765 43210`, `0091…` and `0…` (`test_scrub_pii_catches_how_students_type_phone_numbers`).
Fixed (**medium**): a draft stuffed with candidate values no longer exempts them from the answer
guard (`guard._single_attempt`; `test_a_stuffed_draft_exempts_nothing`).

Eval record: both evals pass ("AI eval results" below).

Open: `late` and `error` rows don't count against the daily tutor cap (bounded by questions
answered; the provider spend limit is the backstop).

## 7. Privacy endpoints (spec 014) — PASS
Evidence: export is admin-only, rate limited (5/h), the audit row commits before the body, a safe
filename, erased students 404, no answer keys or internal fields
(`test_export_has_every_section_and_only_that_student`); the CLI export uses umask 077 and refuses
the repo or a non-empty folder; erasure bans first, commits once, completes per student under the
tutor lock with `SKIP LOCKED`, anonymises and deletes enrolment and assignment links
(`test_erasure_db`); erased students are excluded everywhere; audit meta holds scalars only, no
code updates or deletes it, reads are admin-only (`test_audit_db`); the consent gate and
withdrawal share the per-student lock.

Fixed: an existing empty export folder is now chmod 0700.

Open (info): append-only audit is enforced by the app (no DB trigger); an erasure request doesn't
take the tutor lock (text is purged at completion, as the spec says).

## 8. Secrets — PASS
Evidence: secrets are `SecretStr`, `hide_input_in_errors`, `hide_parameters`; logs carry class
names and statuses only; AI errors are fixed strings raised `from None`; `before_send` scrubbing
with a fake-secret test and an end-to-end SDK test (`test_observability.py`); the frontend's
`dataCollection` collects nothing; workflows keep secrets in the `production` environment, gate
steps echo booleans only; backups are piped into gpg with the passphrase on a file descriptor;
`.gitignore` verified with `git check-ignore`; **gitleaks over the full history (170 commits):
one false positive, allow-listed by fingerprint below**; the load test's HS256 secret lives in
child environments only; the bundle reads `VITE_*` only.

Fixed: CI now runs with `permissions: contents: read` and `persist-credentials: false` everywhere.

Open (accepted): the repository-level `TEST_DATABASE_URL` is readable by same-repo branches (test
project, seeded data only); `pg_dump`/`psql` get the backup URL on argv (single-tenant runners).

## 9. Data at rest and in transit — PASS
Evidence: RLS on every table in `public` (each migration; `test_rls_db.py` on a fresh
downgrade/upgrade; `restore_check.sh` re-checks restored backups); no views, functions or grants in
`public`; SSL required to non-local Postgres hosts (`normalize_db_url`, `test_config.py`); backups
AES256-encrypted, never written in plain, 14-day retention, restore-checked; CLI exports 0600/0700;
HSTS in production; https `APP_URL` enforced.

Fixed (**medium**): database connections can now verify the server certificate:
`DATABASE_SSL_ROOT_CERT` (Supabase's CA) makes the API, alembic, the test-DB lock and the load test
verify certificate and host name (`with_root_cert`; `test_root_cert_makes_the_connection_verify`).
Fixed (**medium**): backups never fall back to plaintext (`PGSSLMODE=require`, or `verify-full`
with the CA; a URL that weakens `sslmode` is refused).
Fixed: production refuses `http://` for `SUPABASE_URL` and `TUTOR_BASE_URL` and a weak `sslmode`
in `DATABASE_URL` (`test_production_guard_refuses_plain_transport`); the SPA sends HSTS; the
runbook's decrypt step uses `umask 077`.

Open (owner: user): set `DATABASE_SSL_ROOT_CERT` in production (deploy checklist). Without it the
connection is encrypted but the certificate isn't verified.

## 10. Headers, CORS, rate limits, body cap, error responses — PASS
Evidence: middleware order request id → CORS → headers → body cap → catch-all; the header set on
every response, including 404/413/500 (`test_middleware.py`); CORS reflects only listed origins,
`*` refused in production; rate limits per user before the DB lookup, per IP for bad tokens,
monotonic clock, `Retry-After`, hourly buckets kept until refilled (`test_ratelimit.py`); body cap
from every `Content-Length` and while reading chunked bodies; 500s never carry a trace; request ids
validated.

Fixed: 422 responses no longer echo the input (they echoed passwords and pasted name lists:
`test_422_does_not_echo_the_input`); CORS no longer allows credentials (bearer tokens, no
cookies).

Open: the unauthenticated per-IP bucket map has no size cap (needs ~1M source addresses in
10 minutes); `ENVIRONMENT` defaults to development (deploy checklist: must be set).

## 11. Dependencies — PASS
Evidence: `make audit-py` clean (certifi upgraded for PYSEC-2026-4320); `pnpm audit --prod`: one
low (below); dev-only highs (undici via jsdom, minimatch via eslint) don't reach `dist/`; lockfiles
committed, installs frozen everywhere; the `loadtest` group stays out of the default install;
Pyodide pinned (314.0.7) and confined to a worker without the session token.

Fixed (**medium**): every GitHub Action pinned to a commit SHA, with Dependabot for updates
(`.github/dependabot.yml`). Fixed: the gitleaks tarball's SHA-256 is hard-coded; pip-audit pinned
(2.10.1); the production job runs `--no-dev`.

Open: Pyodide from jsDelivr has no integrity check (the CSP now allows only its pinned folder;
self-hosting it would remove the CDN entirely).

## 12. Client — PASS
Evidence: sign-out clears the session, query cache and in-memory temp passwords; no secrets in
`dist/` (grep for `service_role`, `DEEPSEEK`, `sk-`, `postgres://`, private keys: none; no source
maps); the CSP matches spec §4, no inline scripts; the only HTML sinks are KaTeX output and
Mermaid in strict mode; no open redirects; `target="_blank"` links have `rel="noopener
noreferrer"`; the Pyodide worker never sees the token.

Fixed: a sign-out in another tab (or a failed refresh) now also clears the query cache and the
temp-password slips, and signing in clears old slips; `script-src`/`connect-src` allow only the
pinned Pyodide folder, not all of jsDelivr (needs the end-of-project browser check under
`pnpm preview`).

## AI eval results
Run 2026-11-12 (spec 015 review; no earlier result was recorded in the repo), against the live
models with the key in `backend/.env`:

| Eval | Model | Runs | Result |
|---|---|---|---|
| `app tutor eval --runs 3` (33 cases, spec 009) | `deepseek-flash` (judge `deepseek-v4-pro`) | 99 | **PASS**: 0 answer leaks, 0 step leaks, 0 confirmations, 0 wrong categories, 0 guard hits on final replies, 0 unverified runs; on-rung 100%, helpful 100%. Tokens: tutor 172.6k in / 15.8k out, judge 104.8k in / 47.3k out |
| `app teacher-ai eval --runs 3` (10 cases, spec 011) | `deepseek-v4-pro` | 30 | **PASS**: 0 unsupported claims, 0 overclaimed causes, 0 runs without a claim, 0 unverified runs; vague quantities 0%, actionable notes 98% (`thin_data`: 1 ok, 2 partial). Tokens: writer 26.9k in (22.1k cached) / 77.3k out, judge 25.1k in / 49.1k out |

These are the release gate for prompt or model changes (re-run and record here).

## Audit ignores
Ids here are skipped by `scripts/pip_audit_filter.py`. Every line needs a reason and a date to
revisit; `pnpm audit` fails only at high and above, so lows are listed under "Known lows" instead.

| ID | Reason | Revisit |
|---|---|---|

## Secret-scan allow-list (`.gitleaksignore`)
| Fingerprint | Reason | Date |
|---|---|---|
| `d27b06d…:backend/.env.example:generic-api-key:33` | False positive: `DEEPSEEK_API_KEY=` was empty and the rule read the next line (`TUTOR_ENABLED=true`, 18 chars) as its value. No key was ever committed; nothing to rotate | 2026-11-12 |

## Known lows (dependencies)
| ID | Package | Why it stays | Revisit |
|---|---|---|---|
| GHSA-238p-pmpm-9mq7 | katex 0.16.47 (via `rehype-katex` 7.0.1, which pins `^0.16`) | Low. Needs an existing prototype pollution to bypass `trust`; we never enable `trust`, and content is authored in the repo. Fixed in katex ≥ 0.18.2; forcing it under rehype-katex would change lesson maths rendering, so it waits for a rehype-katex release | 2027-01-15 |

## Fixed while adding the scan (2026-11-12)
- certifi 2026.7.22 → 2026.10.23 (PYSEC-2026-4320), via `uv lock --upgrade-package certifi`.
