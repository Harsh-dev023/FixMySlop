"""
Report builder — takes a list of Issue objects and assembles
a structured ScanReport with scoring and export methods.
"""
import csv
import io
import json
import dataclasses
from collections import Counter
from datetime import datetime
from pathlib import Path
from core.issue import Issue, ScanReport
from core.slop.engine import slop_score, grade
from core.slop.brief import build_fix_brief, compact_findings
from core.slop.sarif import to_sarif
from macros import (
    SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM,
    REPORT_FORMAT_MARKDOWN, REPORT_FORMAT_HTML, REPORT_FORMAT_JSON,
    REPORT_FORMAT_CSV, REPORT_FORMAT_PDF, REPORT_FORMAT_SARIF, REPORT_FORMAT_PROMPT,
    APP_NAME, APP_VERSION, SEVERITY_RANK,
    SCAN_MODE_DEEP, DEFAULT_SCAN_MODE,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def _scan_mode_summary(scan_mode: str) -> str:
    """Format the scan mode label for summaries and exports."""
    if scan_mode == "rules":
        return "RULES (deterministic)"
    return "DEEP 🔍" if scan_mode == SCAN_MODE_DEEP else "TURBO ⚡"


def severity_sort_key(issue: Issue):
    """Sort by real severity order (not alphabetical), then file and line."""
    return (SEVERITY_RANK.get(issue.severity, 9), issue.file_path, issue.line_start)


def relative_path(report: ScanReport, file_path: str) -> str:
    """Path relative to the scanned root (POSIX), falling back to the input."""
    base = Path(report.repo_path)
    if base.is_file():
        base = base.parent
    try:
        return Path(file_path).resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(file_path).as_posix()


def _strip_emojis_for_pdf(text: str) -> str:
    """Replace emojis with PDF-safe plain text."""
    replacements = {
        "⚡": "[TURBO]",
        "🔍": "[DEEP]",
        "⚠": "[!]",
        "✓": "[OK]",
        "⏳": "[...]",
        "🔒": "[SEC]",
        "📊": "[STATS]",
    }
    for emoji, replacement in replacements.items():
        text = text.replace(emoji, replacement)
    # Helvetica in fpdf2 expects latin-1 text unless custom Unicode fonts are used.
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _pdf_safe_text(value) -> str:
    """Coerce values to string and remove unsupported emoji glyphs for PDF fonts."""
    return _strip_emojis_for_pdf(str(value))


class ReportBuilder:
    """
    Assembles a ScanReport from issues and exports to
    Markdown, HTML, JSON, CSV, SARIF, an agent fix brief, or PDF.
    Computes a 'slop score' (0-100) representing overall debt level.
    """

    SEVERITY_WEIGHTS = {
        SEVERITY_CRITICAL: 10,
        SEVERITY_HIGH: 5,
        SEVERITY_MEDIUM: 2,
    }

    def build(
        self,
        repo_path: str,
        issues: list[Issue],
        total_files: int,
        scanned_files: int,
        scan_time_s: float,
        model_used: str,
        scan_mode: str = DEFAULT_SCAN_MODE,
        lines_scanned: int = 0,
    ) -> ScanReport:
        """Build and return a ScanReport from raw scan data.

        With lines_scanned the score is a density per 1k lines (comparable across
        repos of any size); without it, the legacy per-file formula is used.
        """
        report = ScanReport(
            repo_path=repo_path,
            scan_time_s=scan_time_s,
            total_files=total_files,
            scanned_files=scanned_files,
            issues=issues,
            model_used=model_used,
            scan_mode=scan_mode,
            lines_scanned=lines_scanned,
        )
        if lines_scanned > 0:
            report.slop_score = slop_score(issues, lines_scanned)
        else:
            report.slop_score = self._compute_slop_score(issues, scanned_files)
        report.grade = grade(report.slop_score)
        logger.info(
            "Report built: %d issues, slop score %.1f",
            len(issues), report.slop_score,
        )
        return report

    def _compute_slop_score(self, issues: list[Issue], file_count: int) -> float:
        """Compute 0-100 slop score based on weighted issue counts per file."""
        if file_count == 0:
            return 0.0
        total_weight = sum(
            self.SEVERITY_WEIGHTS.get(i.severity, 1) for i in issues
        )
        score = min(100.0, (total_weight / (file_count * 10)) * 100)
        return round(score, 1)

    def export(self, report: ScanReport, fmt: str = REPORT_FORMAT_MARKDOWN) -> str:
        """Export the report to the requested text format."""
        if fmt == REPORT_FORMAT_JSON:
            return self._to_json(report)
        elif fmt == REPORT_FORMAT_HTML:
            return self._to_html(report)
        elif fmt == REPORT_FORMAT_CSV:
            return self._to_csv(report)
        elif fmt == REPORT_FORMAT_PDF:
            return self._to_html(report)
        elif fmt == REPORT_FORMAT_SARIF:
            return to_sarif(report, lambda p: relative_path(report, p))
        elif fmt == "compact":
            summary = (f"FixMySlop: {len(report.issues)} issues, slop score {report.slop_score:g}/100 "
                       f"(grade {report.grade}), {report.scanned_files} files")
            return summary + "\n" + compact_findings(report.issues, lambda p: relative_path(report, p))
        elif fmt == REPORT_FORMAT_PROMPT:
            return build_fix_brief(report.issues, lambda p: relative_path(report, p),
                                   design_context=report.design_context)
        else:
            return self._to_markdown(report)

    def export_pdf(self, report: ScanReport, output_path: str):
        """Export report as a PDF file. Requires fpdf2."""
        try:
            from fpdf import FPDF
        except ImportError:
            logger.warning("fpdf2 not installed — saving as HTML instead")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(self._to_html(report))
            logger.info("Install fpdf2 for PDF: pip install fpdf2")
            return

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Title
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(
            0,
            12,
            _pdf_safe_text(f"{APP_NAME} Audit Report"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(4)

        # Metadata
        pdf.set_font("Helvetica", "", 10)
        meta = [
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Repo: {report.repo_path}",
            f"Slop Score: {report.slop_score}/100" + (f" (grade {report.grade})" if report.grade else ""),
            f"Mode: {_scan_mode_summary(report.scan_mode)}",
            f"Model: {report.model_used}",
            f"Files: {report.scanned_files}/{report.total_files}",
            f"Issues: {len(report.issues)}",
            f"Scan Time: {report.scan_time_s:.1f}s",
        ]
        for line in meta:
            pdf.cell(0, 6, _pdf_safe_text(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

        # Issues table header
        pdf.set_font("Helvetica", "B", 9)
        col_w = [22, 55, 22, 30, 60]
        headers = ["Severity", "File", "Lines", "Category", "Title"]
        for w, h in zip(col_w, headers):
            pdf.cell(w, 8, _pdf_safe_text(h), border=1)
        pdf.ln()

        # Issues table rows
        pdf.set_font("Helvetica", "", 8)
        for issue in sorted(report.issues, key=severity_sort_key):
            pdf.cell(col_w[0], 7, _pdf_safe_text(issue.severity), border=1)
            pdf.cell(col_w[1], 7, _pdf_safe_text(relative_path(report, issue.file_path)[-30:]), border=1)
            pdf.cell(
                col_w[2],
                7,
                _pdf_safe_text(f"{issue.line_start}-{issue.line_end}"),
                border=1,
            )
            pdf.cell(col_w[3], 7, _pdf_safe_text(issue.category[:16]), border=1)
            pdf.cell(col_w[4], 7, _pdf_safe_text(issue.title[:32]), border=1)
            pdf.ln()

        pdf.output(output_path)
        logger.info("PDF report saved: %s", output_path)

    def _to_csv(self, report: ScanReport) -> str:
        """Export report as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Severity", "File", "Line Start", "Line End",
            "Category", "Rule ID", "Title", "Description",
            "Evidence", "Suggested Fix", "Source Tool",
        ])
        for issue in sorted(report.issues, key=severity_sort_key):
            writer.writerow([
                issue.severity,
                relative_path(report, issue.file_path),
                issue.line_start,
                issue.line_end,
                issue.category,
                issue.rule_id,
                issue.title,
                issue.description,
                issue.evidence,
                issue.suggested_fix,
                issue.source_tool,
            ])
        return output.getvalue()

    def _to_markdown(self, report: ScanReport) -> str:
        """Export report as Markdown."""
        counts = Counter(i.severity for i in report.issues)
        breakdown = " · ".join(f"{sev}: {counts[sev]}" for sev in SEVERITY_RANK if counts.get(sev))
        grade_text = f" (grade {report.grade})" if report.grade else ""
        lines = [
            f"# {APP_NAME} Audit Report",
            f"**Version:** {APP_VERSION}  ",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
            f"**Repo:** `{report.repo_path}`  ",
            f"**Slop Score:** {report.slop_score}/100{grade_text}  ",
            f"**Mode:** {_scan_mode_summary(report.scan_mode)}  ",
            f"**Model:** {report.model_used}  ",
            f"**Files Scanned:** {report.scanned_files}/{report.total_files}  ",
            f"**Issues Found:** {len(report.issues)}" + (f" ({breakdown})" if breakdown else "") + "  ",
            "",
            "## Issues",
            "",
        ]
        for issue in sorted(report.issues, key=severity_sort_key):
            lines += [
                f"### [{issue.severity}] {issue.title}",
                f"**File:** `{relative_path(report, issue.file_path)}` "
                f"(lines {issue.line_start}-{issue.line_end})  ",
                f"**Category:** {issue.category}  ",
                f"**Rule:** `{issue.rule_id}` ({issue.source_tool})  ",
                "",
                issue.description,
                "",
            ]
            if issue.evidence:
                lines += ["```", issue.evidence, "```", ""]
            if issue.suggested_fix:
                lines += [f"**Fix:** {issue.suggested_fix}", ""]
        return "\n".join(lines)

    def _to_json(self, report: ScanReport) -> str:
        """Export report as JSON."""
        return json.dumps(dataclasses.asdict(report), indent=2)

    def _to_html(self, report: ScanReport) -> str:
        """Export report as the interactive, self-contained HTML page."""
        from core.html_report import render_html
        return render_html(report, lambda p: relative_path(report, p))
