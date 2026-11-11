# Runbook: privacy requests and jobs (spec 014)

Who does what when a parent, a student or a school asks about a student's data. Students are minors:
never paste names, usernames or exported files into tickets, chat or AI tools.

## Tutor consent
- The school prints the forms (class → Students → **Print consent forms**), collects the signed paper
  forms and keeps them. Nothing written on the paper goes into the app.
- A teacher ticks the students whose forms came back (class → Students → select → **Record consent**).
  Without consent the AI tutor stays locked; everything else works.
- **Withdrawal**: the parent tells the class teacher, who selects the student → **Withdraw consent**.
  The tutor locks at once and the student's tutor chat text is deleted at once.

## Access request (a copy of the data)
1. The school admin opens the student (class → student → **Privacy** card, or **Students** → row
   menu for a student with no class) → **Download data (JSON)**.
2. The admin gives the file to the parent through the school's own channel and deletes their local
   copy. The download is recorded in the audit log.
3. The file holds the account, consent history, classes, learning records, XP, reviews, quizzes,
   placement results, assignments, tutor chats and per-student AI summaries. It never holds answer
   keys or other students' data.

Whole school (operator only, e.g. when a school leaves):
```
cd backend && uv run app privacy export --org CODE --out /path/outside/the/repo/CODE-export
```
The folder must be empty and outside any git checkout (including a home folder that is itself a dotfiles
repo); files are written readable by you only. One audit event per student is written
(`source: cli`). Hand the folder over encrypted and delete it afterwards.

## Erasure request
1. The school admin opens the student → **Erase student…** and types the username.
2. The student is signed out and deactivated at once. The erasure runs **7 days** later ("Erasure
   after {date}" badge). Until then the admin can **Cancel erasure** (the student stays deactivated;
   reactivate them with the usual switch) and can still download the data.
3. At completion the account is anonymised ("Erased student", random username), the sign-in account
   is deleted from Supabase, tutor chat text is deleted, and class and assignment links are removed.
   Learning records are kept without a name (class statistics don't change).

## Running the jobs
`app privacy run-due` completes due erasures and then purges tutor chat text older than 180 days.
It is idempotent and safe to run twice at once.

- **Scheduled**: `.github/workflows/privacy-jobs.yml` runs it daily at 02:00 IST once the secrets
  `PROD_DATABASE_URL`, `PROD_SUPABASE_URL` and `PROD_SUPABASE_SERVICE_ROLE_KEY` exist. Without them it
  ends green with "skipped: no production secrets". Store them as **environment secrets** of a GitHub
  Environment named `production` whose deployment branches are limited to `main` (add a required
  reviewer for manual runs), never as repository secrets: those can be read by a workflow on any branch.
  Pinning the workflow's actions to commit SHAs is part of spec 015's CI hardening.
- **Until production is deployed, run it by hand** (at least daily while an erasure is pending):
  ```
  cd backend && uv run app privacy run-due
  ```
  It prints `Erasures completed: N, failed: M.` and exits 1 when an erasure failed (usually the
  Supabase admin API was unreachable). Failed students are listed by id only and retried on the next
  run; nothing is half-done.
- An auth user already deleted by hand in the Supabase dashboard counts as done.

## Audit log
Admins see every consent change, data download, erasure step, password reset and (de)activation
under **Audit log**. Rows are never edited or deleted by the app.
