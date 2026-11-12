# Security review

Spec 015 §5. The full dated checklist (12 areas, evidence and results) is completed in spec 015
PR 3. This file already holds the dependency-audit record that `make audit` and the CI `security`
job read.

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
