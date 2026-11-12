# Pilot readiness

Gates that must be closed before real students use the app and that are **not** feature specs: they need people
outside the build loop. Code gates live in the specs (docs/ROADMAP.md). Tick a line only with a date and who closed
it (role, never a personal contact).

## 1. Legal review (DPDP Act 2023 and Rules)
Owner: platform owner, with a lawyer. Input: `backend/app/privacy/notice.md` (spec 014), docs/PRD.md → Constraints,
docs/ARCHITECTURE.md → AI.

The build made these assumptions (spec 014). Each needs a yes, or a change request:

- [ ] Students may **learn without parental consent** because the school is the data fiduciary for classroom
      activity and we process on its instruction. *If no: add a sign-in consent gate (small follow-up, spec 014 →
      Extension points).*
- [ ] A **teacher's tick, with the signed paper form kept by the school**, is acceptable as verifiable parental
      consent for the AI tutor.
- [ ] Sending **tutor chat text to DeepSeek (servers in China)** is acceptable with that consent (no names or ids
      are sent; emails and phone numbers are scrubbed; text is kept 180 days).
- [ ] Sending **pseudonymised class statistics to DeepSeek** for teacher summaries needs no parental consent.
- [ ] **Erasure by anonymisation** is enough: the name, username and sign-in are removed and tutor text wiped, but
      anonymous learning rows (including submitted answers and code) are kept. *If no: also null
      `attempt.response` at erasure.*
- [ ] **Sentry** (EU) receiving stack traces with internal ids only is acceptable (spec 015).
- [ ] The wording of the parent notice and form; the school–platform data processing agreement.
- [ ] The `[OPERATOR NAME]` and `[CONTACT]` placeholders in `backend/app/privacy/notice.md` are filled in.
- [ ] Retention periods: tutor text 180 days; learning data for as long as the school uses the app; backups 14 days.

## 2. Teacher content review
Owner: content lead. Tracker: docs/content-review.md.

- [ ] Every row in docs/content-review.md is `teacher-reviewed` (maths, physics; Python by a computer-science
      teacher if available). Findings come back as normal content PRs.

## 3. Production deployment
Owner: platform owner. Checklist: docs/runbooks/deploy-checklist.md (written in spec 015).

- [ ] Production Supabase project (public sign-up off, redirect allow-list), API host and SPA host are live.
- [ ] Secrets set in GitHub: `PROD_*` (privacy jobs, spec 014) and `BACKUP_*` (nightly backup, spec 015); both
      workflows have run green against production once.
- [ ] Sentry project created (EU) and DSNs set; one test error seen from the API and from the browser.
- [ ] A restore drill from a production backup is recorded in docs/runbooks/backup-restore.md.
- [ ] Spend limits set in the DeepSeek console; tutor and summary caps confirmed.
- [ ] docs/security-review.md is less than a month old on the day the pilot starts (repeat it otherwise).

## 4. School onboarding (per school)
- [ ] School created (`app org create`), teachers invited, classes and students created.
- [ ] Consent forms printed, collected and recorded for the students who will use the AI tutor.
- [ ] Teachers shown: the dashboard, assignments, placement, how to withdraw consent and whom to ask for an export
      or erasure.
