"""
SARIF 2.1.0 export, so findings show up as GitHub code-scanning annotations.
"""
import json
from typing import Callable

from fixmyslop.core.issue import ScanReport
from fixmyslop.core.slop.rule import RULES
from fixmyslop.macros import (
    APP_NAME, APP_VERSION, APP_URL,
    SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM,
)

_LEVELS = {SEVERITY_CRITICAL: "error", SEVERITY_HIGH: "error", SEVERITY_MEDIUM: "warning"}
_SECURITY_SEVERITY = {SEVERITY_CRITICAL: "9.5", SEVERITY_HIGH: "7.5", SEVERITY_MEDIUM: "5.0"}


def to_sarif(report: ScanReport, relpath: Callable[[str], str]) -> str:
    """Serialize a ScanReport as a SARIF log."""
    rules_meta: dict[str, dict] = {}
    results = []
    for issue in report.issues:
        rule_id = issue.rule_id or f"{issue.source_tool}/unknown"
        if issue.source_tool not in ("fixmyslop",) and "/" not in rule_id:
            rule_id = f"{issue.source_tool}/{rule_id}"
        if rule_id not in rules_meta:
            known = RULES.get(issue.rule_id)
            meta = {
                "id": rule_id,
                "name": rule_id.replace("/", "-"),
                "shortDescription": {"text": known.title if known else issue.title[:120]},
                "fullDescription": {"text": known.why if known else issue.description[:500]},
                "help": {"text": known.fix if known else (issue.suggested_fix or issue.description)},
                "properties": {"tags": [issue.category]},
            }
            if issue.category == "Security":
                meta["properties"]["security-severity"] = _SECURITY_SEVERITY.get(issue.severity, "3.0")
            if known:
                meta["helpUri"] = f"{APP_URL}#rules"
            rules_meta[rule_id] = meta
        results.append({
            "ruleId": rule_id,
            "level": _LEVELS.get(issue.severity, "note"),
            "message": {"text": f"{issue.title}. {issue.suggested_fix or ''}".strip()},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": relpath(issue.file_path)},
                    "region": {
                        "startLine": max(1, issue.line_start),
                        "endLine": max(1, issue.line_end or issue.line_start),
                    },
                },
            }],
        })
    log = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "informationUri": APP_URL,
                "rules": list(rules_meta.values()),
            }},
            "results": results,
        }],
    }
    return json.dumps(log, indent=2)
