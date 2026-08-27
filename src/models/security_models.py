"""Strix scan result schemas & CVSS audit reports.

Description: Pydantic models representing Strix SAST/DAST findings and the
             aggregated CVSS-scored audit report.
Need: Security findings must be structured and scored consistently so the
      Gate 4 HITL reviewer can quickly assess severity and risk.
Motive: Standardize how vulnerabilities are represented across scans so
        reports are comparable over time and across projects.
"""

from pydantic import BaseModel


class Finding(BaseModel):
    title: str
    cvss_score: float
    severity: str
    description: str


class SecurityAuditReport(BaseModel):
    target: str
    findings: list[Finding]
    overall_risk: str
