"""`crypto_ethereum.token_transfers` source-of-truth violation
test.

The pipeline must DERIVE token movements from logs (Transfer events) AND
traces (transfer/transferFrom internal calls), NOT pull them from BQ's
pre-aggregated `crypto_ethereum.token_transfers` table.

This test recursively greps `ingestion/`, `decoder/`, `protocols/` for the
literal string `crypto_ethereum.token_transfers` (case-insensitive) and
asserts ZERO matches. The validator module is allowed (and is the only
location where the string may appear).
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_no_token_transfers_table_in_pipeline_modules() -> None:
    """Recursive grep enforcement.

    Allowed locations:
      - reconciliation/bq_validator.py (or anything in reconciliation/ named
        *validator*)
      - tests/                  (test files reference it for verification)
    """
    forbidden_dirs = ["ingestion", "decoder", "protocols"]
    pattern = re.compile(r"crypto_ethereum\.token_transfers", re.IGNORECASE)

    violations: list[str] = []
    for d in forbidden_dirs:
        directory = PROJECT_ROOT / d
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{line_no}: {line.strip()}")

    assert violations == [], (
        "ingestion/decoder/protocols must NOT reference "
        "`crypto_ethereum.token_transfers`. Offenders:\n" + "\n".join(violations)
    )
