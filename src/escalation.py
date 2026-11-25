"""Escalation routing.

Routes HIGH (immediate) and MEDIUM (priority) case summaries. Every routed case is logged
(CloudWatch Logs on AWS). When ALERT_TOPIC_ARN is set, cases whose tier is listed in
escalation.sns_tiers (HIGH by default) are also published to that Amazon SNS topic, which
e-mails Sympany's risk team; the scan job publishes its run summary to the same topic
(``publish_alert``).
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from .config import aws_region
from .models import CaseFile

log = logging.getLogger(__name__)


def case_summary(case: CaseFile) -> str:
    return (
        f"[{case.severity}] {case.case_id} | {case.risk_category} "
        f"({case.confidence:.0%} conf) | {case.platform}:{case.source}\n"
        f"  Urgency: {case.mitigation_urgency} | RACM: {case.racm_ref} | KRI: {case.kri_ref}\n"
        f"  Rationale: {case.rationale}\n"
        f"  Indicators: {', '.join(case.indicators) or '-'}\n"
        f"  Link: {case.url or 'n/a'}"
    )


class BaseEscalator(ABC):
    @abstractmethod
    def route(self, case: CaseFile, recipients: list[str]) -> None: ...


class LogEscalator(BaseEscalator):
    """Default escalator: emits the routed summary to the log/stdout."""

    def route(self, case: CaseFile, recipients: list[str]) -> None:
        to = ", ".join(recipients) if recipients else "(no recipients configured)"
        log.warning("ESCALATION -> %s\n%s", to, case_summary(case))


def publish_alert(subject: str, message: str) -> bool:
    """Publish to the Amazon SNS alert topic (ALERT_TOPIC_ARN). False when not configured."""
    topic = os.environ.get("ALERT_TOPIC_ARN", "").strip()
    if not topic:
        return False
    try:
        import boto3

        boto3.client("sns", region_name=aws_region()).publish(
            TopicArn=topic, Subject=subject[:100], Message=message[:250_000])
        return True
    except Exception as exc:  # noqa: BLE001 — an alert failure must not stop a scan
        log.warning("SNS publish failed: %s", exc)
        return False


class Escalation:
    def __init__(self, escalation_cfg: dict, escalator: BaseEscalator | None = None) -> None:
        self._cfg = escalation_cfg or {}
        self._escalator = escalator or LogEscalator()
        self._sns_tiers = {str(t).upper() for t in self._cfg.get("sns_tiers", ["HIGH"])}

    def handle(self, case: CaseFile, tier: str) -> None:
        if tier == "HIGH":
            self._escalator.route(case, self._cfg.get("high", []))
        elif tier == "MEDIUM":
            self._escalator.route(case, self._cfg.get("medium", []))
        # LOW is log-only; no routing.
        if tier in self._sns_tiers:
            publish_alert(f"[{tier}] {case.risk_category} risk on {case.platform}", case_summary(case))
