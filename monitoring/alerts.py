"""Alert delivery for failed CheckResults.

Channels are pluggable; default implementation posts to a webhook (Slack /
PagerDuty / etc.) read from `ALERT_WEBHOOK_URL`. The runbook for each alert is
documented in `docs/runbook.md`.
"""

from __future__ import annotations

from typing import Literal

from reconciliation.checks import CheckResult

Channel = Literal["webhook", "stdout", "noop"]


def emit_alert(check_result: CheckResult, channel: Channel = "webhook") -> None:
    """No-op if `check_result.passed` is True. Otherwise dispatches to the channel."""
    raise NotImplementedError(
        "Planned production sink: alert delivery depends on the team's Slack, "
        "PagerDuty, or webhook destination."
    )


def format_alert_message(check_result: CheckResult) -> str:
    """Markdown message body. Includes a link to the relevant runbook section."""
    raise NotImplementedError(
        "Planned production formatter: choose the final alert format with the "
        "runtime alerting destination."
    )
