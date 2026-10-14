"""
Report builder — takes a list of Issue objects and assembles
a structured ScanReport with scoring and export methods.
"""
import csv
import html
import io
import json
import dataclasses
from collections import Counter, defaultdict
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
    APP_NAME, APP_VERSION, SEVERITY_RANK, SEVERITY_COLORS,
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
            return build_fix_brief(report.issues, lambda p: relative_path(report, p))
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
        """Export report as a standalone, self-contained HTML page."""
        esc = html.escape
        by_file: dict[str, list[Issue]] = defaultdict(list)
        for issue in report.issues:
            by_file[relative_path(report, issue.file_path)].append(issue)
        counts = Counter(i.severity for i in report.issues)
        chips = "".join(
            f"<span class=\"chip\" style=\"--c:{SEVERITY_COLORS.get(sev, '#888')}\">{sev} {counts[sev]}</span>"
            for sev in SEVERITY_RANK if counts.get(sev)
        )

        def file_rank(item):
            path, issues = item
            return (min(SEVERITY_RANK.get(i.severity, 9) for i in issues), path)

        sections = []
        for path, issues in sorted(by_file.items(), key=file_rank):
            rows = []
            for issue in sorted(issues, key=lambda i: (i.line_start, SEVERITY_RANK.get(i.severity, 9))):
                color = SEVERITY_COLORS.get(issue.severity, "#888")
                evidence = f"<pre>{esc(issue.evidence)}</pre>" if issue.evidence else ""
                fix = f"<p class=\"fix\"><b>Fix:</b> {esc(issue.suggested_fix)}</p>" if issue.suggested_fix else ""
                rows.append(
                    f"<li><div class=\"head\"><span class=\"sev\" style=\"--c:{color}\">{esc(issue.severity)}</span>"
                    f"<span class=\"ln\">L{issue.line_start}</span><code>{esc(issue.rule_id)}</code>"
                    f"<b>{esc(issue.title)}</b></div><p>{esc(issue.description)}</p>{evidence}{fix}</li>"
                )
            sections.append(
                f"<section><h2><code>{esc(path)}</code> <small>{len(issues)}</small></h2>"
                f"<ul>{''.join(rows)}</ul></section>"
            )
        body = "".join(sections) or "<p class=\"clean\">No issues found.</p>"
        meta = (
            f"{esc(report.repo_path)} · {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
            f"{report.scanned_files} files · {report.lines_scanned} lines · "
            f"{report.scan_time_s:.1f}s · {esc(report.model_used)}"
        )
        return "\n".join([
            "<!DOCTYPE html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            f"<title>{APP_NAME} Audit Report</title>",
            f"<style>{_HTML_CSS}</style>",
            "</head>",
            "<body><main>",
            f"<h1>{APP_NAME} Audit Report</h1>",
            f"<p class=\"meta\">{meta}</p>",
            f"<div class=\"score\"><div><b>{report.slop_score:g}</b>/100 slop score</div>"
            f"<div class=\"grade\">Grade {esc(report.grade or '-')}</div>"
            f"<div>{len(report.issues)} issues {chips}</div></div>",
            body,
            "</main></body>",
            "</html>",
        ])


_HTML_CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--line:#e7e5e4;--card:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#0c0a09;--fg:#e7e5e4;--muted:#a8a29e;--line:#292524;--card:#1c1917}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:32px 16px}
h1{font-size:22px;margin:0 0 4px}.meta{color:var(--muted);margin:0 0 20px;overflow-wrap:anywhere}
.score{display:flex;gap:24px;align-items:baseline;flex-wrap:wrap;border:1px solid var(--line);
background:var(--card);padding:16px 20px;border-radius:8px;margin-bottom:24px}
.score b{font-size:40px;line-height:1}.grade{font-size:24px;font-weight:700}
.chip,.sev{border:1px solid var(--c);color:var(--c);border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
.chip{margin-left:6px}section{margin:0 0 20px}h2{font-size:15px;margin:0 0 8px;overflow-wrap:anywhere}
h2 small{color:var(--muted);font-weight:400}ul{list-style:none;margin:0;padding:0}
li{border:1px solid var(--line);background:var(--card);border-radius:6px;padding:10px 14px;margin:0 0 8px}
.head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.ln{color:var(--muted);font-variant-numeric:tabular-nums}
li p{margin:6px 0 0;color:var(--muted)}li p.fix{color:var(--fg)}
pre{background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:8px;overflow-x:auto;
margin:8px 0 0;font:12px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap}
code{font-family:ui-monospace,Consolas,monospace}.clean{font-size:18px}
"""
