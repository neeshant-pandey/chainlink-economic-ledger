"""SQL-ref enforcement for dbt analytics models.

Parses every `dbt/models/analytics/*.sql` file (after stripping SQL comments),
extracts every `{{ ref(...) }}` and `{{ source(...) }}` reference, and asserts:

  - All `ref()` targets are either in `dbt/models/marts/*` OR exactly
    `stg_canonical_blocks`
  - Zero `source()` calls
  - Zero references to `bigquery-public-data.crypto_ethereum.*`, `raw_*`,
    `decoded_*`, or `token_transfers`

Exit 0 = green. Exit 1 = at least one violation; prints the offending file
and the bad reference.

Run as: `uv run python scripts/check_analytics_refs.py`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = REPO_ROOT / "dbt" / "models" / "analytics"
MARTS_DIR = REPO_ROOT / "dbt" / "models" / "marts"

# Whitelisted staging refs (the analytics layering rule allows stg_canonical_blocks specifically).
ALLOWED_STAGING_REFS: frozenset[str] = frozenset({"stg_canonical_blocks"})

# Forbidden raw fragments in any SQL string (post-comment-strip).
FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "bigquery-public-data.crypto_ethereum",
    "crypto_ethereum.token_transfers",
    "token_transfers",
    "raw_",
    "decoded_",
)

# Regex: `{{ ref('<name>') }}` (or double-quoted; allow surrounding whitespace).
REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
# Regex: `{{ source('<x>', '<y>') }}`.
SOURCE_RE = re.compile(r"\{\{\s*source\(")


def _strip_sql_comments(sql: str) -> str:
    """Remove `-- line comments` and `/* block comments */` so we don't false-
    positive on documentation that mentions forbidden fragments."""
    # Block comments
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # Line comments
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def _list_mart_names() -> set[str]:
    """Mart names are file stems under dbt/models/marts/*.sql."""
    return {p.stem for p in MARTS_DIR.glob("*.sql")}


def main() -> int:
    if not ANALYTICS_DIR.exists():
        print(f"FAIL: analytics dir not found: {ANALYTICS_DIR}", file=sys.stderr)
        return 1
    if not MARTS_DIR.exists():
        print(f"FAIL: marts dir not found: {MARTS_DIR}", file=sys.stderr)
        return 1

    marts = _list_mart_names()
    if not marts:
        print(f"FAIL: no mart files found in {MARTS_DIR}", file=sys.stderr)
        return 1

    violations: list[str] = []

    for sql_path in sorted(ANALYTICS_DIR.glob("*.sql")):
        raw = sql_path.read_text()
        stripped = _strip_sql_comments(raw)

        # 1. No `source()` calls.
        if SOURCE_RE.search(stripped):
            violations.append(f"{sql_path.relative_to(REPO_ROOT)}: forbidden source() call")

        # 2. Every ref() must be a mart name or stg_canonical_blocks.
        for match in REF_RE.finditer(stripped):
            ref_name = match.group(1)
            if ref_name in marts:
                continue
            if ref_name in ALLOWED_STAGING_REFS:
                continue
            violations.append(
                f"{sql_path.relative_to(REPO_ROOT)}: ref('{ref_name}') is not a mart "
                f"and not in the allowed staging refs ({sorted(ALLOWED_STAGING_REFS)})"
            )

        # 3. No forbidden raw/decoded/source fragments.
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in stripped:
                violations.append(
                    f"{sql_path.relative_to(REPO_ROOT)}: contains forbidden "
                    f"fragment {fragment!r} (analytics may not read raw/staging "
                    f"decoded or token_transfers)"
                )

    if violations:
        print(f"FAIL: {len(violations)} analytics-ref violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print(
        f"OK: {len(list(ANALYTICS_DIR.glob('*.sql')))} analytics model(s) "
        "ref only marts + stg_canonical_blocks; no source() / raw_ / decoded_ "
        "/ token_transfers / bigquery-public-data references"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
