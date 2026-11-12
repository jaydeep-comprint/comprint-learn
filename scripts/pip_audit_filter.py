"""Spec 015: fail on known vulnerabilities that have a fix (pip-audit has no such mode).

Reads `pip-audit -f json` on stdin. Ignores ids listed in docs/security-review.md under
"## Audit ignores" (a table: id | reason | date to revisit). Exits 1 if anything is left.
"""

import json
import re
import sys
from pathlib import Path

REVIEW = Path(__file__).resolve().parents[1] / "docs" / "security-review.md"


def ignored_ids(text: str) -> set[str]:
    section = text.split("## Audit ignores", 1)
    if len(section) < 2:
        return set()
    body = section[1].split("\n## ", 1)[0]
    ids = set()
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"[A-Za-z]+-[\w-]+", cells[0] or ""):
            ids.add(cells[0])
    return ids


def main() -> int:
    data = json.load(sys.stdin)
    ignore = ignored_ids(REVIEW.read_text()) if REVIEW.exists() else set()
    failing, unfixed = [], []
    seen: set[tuple[str, str]] = set()
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            if (dep["name"], vuln["id"]) in seen:  # pip-audit can list one advisory twice
                continue
            seen.add((dep["name"], vuln["id"]))
            ids = {vuln["id"], *vuln.get("aliases", [])}
            fix = vuln.get("fix_versions") or "none"
            line = f"{dep['name']} {dep['version']}: {vuln['id']} (fix: {fix})"
            if ids & ignore:
                print(f"ignored  {line}")
            elif vuln.get("fix_versions"):
                failing.append(line)
            else:
                unfixed.append(line)
    for line in unfixed:
        print(f"no fix   {line}  (add to docs/security-review.md with a revisit date)")
    for line in failing:
        print(f"FIXABLE  {line}")
    print(
        f"pip-audit: {len(failing)} fixable, {len(unfixed)} without a fix, "
        f"{len(ignore)} ignore entries"
    )
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
