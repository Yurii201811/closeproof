"""Daily and weekly Openclaw risk report stubs."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from .risk_review import RiskFinding


@dataclass(frozen=True)
class RiskReport:
    period: str
    report_date: date
    reviewed_cases: int
    cases_with_findings: int
    findings_by_signal: dict[str, int]
    findings_by_severity: dict[str, int]
    blocked_cases: int
    report_version: str = "openclaw-risk-report-stub-v1"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["report_date"] = self.report_date.isoformat()
        return data


def build_risk_report(
    case_findings: dict[str, tuple[RiskFinding, ...]],
    *,
    period: str = "daily",
    report_date: date | None = None,
) -> RiskReport:
    """Build a machine-readable daily/weekly risk report summary."""

    signal_counter: Counter[str] = Counter()
    severity_counter: Counter[str] = Counter()
    blocked_cases = 0
    for findings in case_findings.values():
        if any(finding.severity.value == "blocker" for finding in findings):
            blocked_cases += 1
        for finding in findings:
            signal_counter[finding.signal.value] += 1
            severity_counter[finding.severity.value] += 1

    return RiskReport(
        period=period,
        report_date=report_date or date.today(),
        reviewed_cases=len(case_findings),
        cases_with_findings=sum(1 for findings in case_findings.values() if findings),
        findings_by_signal=dict(sorted(signal_counter.items())),
        findings_by_severity=dict(sorted(severity_counter.items())),
        blocked_cases=blocked_cases,
    )
