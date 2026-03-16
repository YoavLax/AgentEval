from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agenteval import __version__
from agenteval.core import validate
from agenteval.result import CheckRun, FileType, Severity, ValidationResult

# ---------------------------------------------------------------------------
# ANSI helpers (zero dependencies)
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"

_SEV_SYMBOL = {Severity.ERROR: "✗", Severity.WARNING: "⚠", Severity.INFO: "·"}
_SEV_COLOR = {Severity.ERROR: _RED, Severity.WARNING: _YELLOW, Severity.INFO: _DIM}


def _style(text: str, *codes: str, color: bool = True) -> str:
    """Wrap *text* in ANSI escape codes when *color* is enabled."""
    if not color:
        return text
    return "".join(codes) + text + _RESET


# ---------------------------------------------------------------------------
# Path collection
# ---------------------------------------------------------------------------


def _collect_paths(target: Path) -> list[Path]:
    """Return skill and agent files to validate.

    For a directory: recursively finds all SKILL.md files and all .md files
    located inside an 'agents/' subdirectory.
    For a file: returns it directly.
    """
    if target.is_dir():
        skill_paths = sorted(target.rglob("SKILL.md"))
        agent_paths = sorted(
            p for p in target.rglob("*.md")
            if any(part == "agents" for part in p.parts)
            and p.name != "SKILL.md"
        )
        return skill_paths + agent_paths
    return [target]


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _format_text(results: list[ValidationResult], *, color: bool = False) -> str:
    lines: list[str] = []
    for result in results:
        if result.valid:
            tag = _style("✔ PASS", _BOLD, _GREEN, color=color)
        else:
            tag = _style("✗ FAIL", _BOLD, _RED, color=color)
        lines.append(f"{tag}  {result.path}")

        for d in result.diagnostics:
            sym = _SEV_SYMBOL.get(d.severity, "·")
            sev_col = _SEV_COLOR.get(d.severity, "")
            loc = f"line {d.line}" if d.line is not None else ""
            sev_label = _style(f"{sym} {d.severity.value}", sev_col, color=color)
            rule = _style(d.rule, _DIM, color=color)
            lines.append(f"  {loc:>8}  {sev_label:<18s}  {rule}  {d.message}")
            if d.context:
                ctx = _style(d.context, _DIM, color=color)
                lines.append(f"{'':>12}  {ctx}")

    # summary
    total = len(results)
    passed = sum(1 for r in results if r.valid)
    failed = total - passed
    warn_count = sum(
        1 for r in results for d in r.diagnostics if d.severity == Severity.WARNING
    )
    noun = "file" if total == 1 else "files"

    parts = [
        _style(f"{passed} passed", _GREEN, color=color),
        _style(f"{failed} failed", _RED, color=color) if failed else f"{failed} failed",
    ]
    if warn_count:
        w = f"{warn_count} warning{'s' if warn_count != 1 else ''}"
        parts.append(_style(w, _YELLOW, color=color))

    lines.append(f"\nChecked {total} {noun}: {', '.join(parts)}")
    return "\n".join(lines)


def _format_json(results: list[ValidationResult], version: str) -> str:
    passed = sum(1 for r in results if r.valid)
    payload = {
        "version": version,
        "files_checked": len(results),
        "files_passed": passed,
        "files_failed": len(results) - passed,
        "results": [
            {
                "path": str(r.path),
                "valid": r.valid,
                "diagnostics": [
                    {
                        "rule": d.rule,
                        "severity": d.severity.value,
                        "message": d.message,
                        "line": d.line,
                        "context": d.context,
                    }
                    for d in r.diagnostics
                ],
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

_SEV_HTML_CLASS = {Severity.ERROR: "sev-error", Severity.WARNING: "sev-warn", Severity.INFO: "sev-info"}
_SEV_HTML_LABEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info"}

_HTML_CSS = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0f0f14; color: #d4d4d8;
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      font-size: 14px; min-height: 100vh; padding: 0 0 60px;
    }
    .topbar {
      background: #18181f; border-bottom: 1px solid #2a2a38;
      padding: 14px 32px; display: flex; align-items: center; justify-content: space-between;
    }
    .brand { font-size: 18px; font-weight: 700; letter-spacing: -0.5px; }
    .brand span { color: #7c7cff; }
    .meta { font-size: 12px; color: #6b6b80; }
    .page { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }
    .report-title { font-size: 26px; font-weight: 700; margin-bottom: 6px; color: #f4f4f5; display: flex; align-items: center; gap: 10px; }
    .scan-type-badge { font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; padding: 3px 9px; border-radius: 4px; background: #3b82f6; color: #fff; flex-shrink: 0; }
    .scan-type-badge-agent { background: #8b5cf6; }
    .type-tag { display: inline-block; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; padding: 1px 6px; border-radius: 3px; margin-right: 6px; }
    .type-tag-skill { background: #1d4ed8; color: #bfdbfe; }
    .type-tag-agent { background: #6d28d9; color: #ddd6fe; }
    .report-sub {
      font-size: 12px; color: #6b6b80; margin-bottom: 28px;
      font-family: 'Cascadia Code','Consolas',monospace; word-break: break-all;
    }

    /* ── stat grid ── */
    .summary-grid { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 36px; }
    .stat-card {
      background: #18181f; border: 1px solid #2a2a38; border-radius: 10px;
      padding: 18px 24px; min-width: 110px; flex: 1;
    }
    .stat-val { font-size: 28px; font-weight: 700; line-height: 1.1; color: #f4f4f5; }
    .stat-val.green { color: #4ade80; }
    .stat-val.red   { color: #f87171; }
    .stat-val.yellow{ color: #facc15; }
    .stat-val.blue  { color: #60a5fa; }
    .stat-label { font-size: 11px; color: #6b6b80; text-transform: uppercase; letter-spacing: .08em; margin-top: 4px; }

    /* ── skills overview table (summary tab) ── */
    .skills-table { width: 100%; border-collapse: collapse; margin-top: 4px; }
    .skills-table th {
      text-align: left; font-size: 11px; font-weight: 600; color: #6b6b80;
      text-transform: uppercase; letter-spacing: .08em;
      padding: 8px 14px; border-bottom: 1px solid #2a2a38;
    }
    .skills-table td { padding: 10px 14px; border-bottom: 1px solid #1a1a24; font-size: 13px; vertical-align: middle; }
    .skills-table tr:last-child td { border-bottom: none; }
    .skills-table tr.row-pass:hover { background: #1e1e28; cursor: pointer; }
    .skills-table tr.row-fail:hover { background: #1e1e28; cursor: pointer; }
    .skill-name-link { color: #a5b4fc; text-decoration: none; font-family: 'Cascadia Code','Consolas',monospace; font-size: 12px; }
    .skill-name-link:hover { color: #7c7cff; text-decoration: underline; }

    /* ── sidebar layout (plugin/multi-file view) ── */
    .plugin-layout {
      display: grid; grid-template-columns: 200px 1fr; gap: 0;
      align-items: start;
    }
    .sidebar {
      background: #18181f; border: 1px solid #2a2a38; border-radius: 10px;
      padding: 8px 0; position: sticky; top: 20px;
      max-height: calc(100vh - 140px); overflow-y: auto;
      margin-right: 24px;
    }
    .sidebar-summary-btn {
      display: flex; align-items: center; width: 100%; background: none; border: none;
      text-align: left; color: #d4d4d8; font-size: 13px; font-weight: 500;
      padding: 9px 16px; cursor: pointer; transition: background .12s, color .12s;
      border-left: 3px solid transparent; gap: 8px;
    }
    .sidebar-summary-btn:hover { background: #1e1e28; color: #f4f4f5; }
    .sidebar-summary-btn.active {
      background: #1e1e28; color: #f4f4f5; border-left-color: #7c7cff; font-weight: 600;
    }
    .sidebar-section-lbl {
      font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em;
      color: #52525b; padding: 12px 16px 4px; user-select: none;
    }
    .sidebar-item {
      display: flex; align-items: center; width: 100%; background: none; border: none;
      text-align: left; color: #a1a1aa; font-size: 12px;
      padding: 7px 12px 7px 16px; cursor: pointer; transition: background .12s, color .12s;
      border-left: 3px solid transparent; gap: 6px;
    }
    .sidebar-item:hover { background: #1e1e28; color: #d4d4d8; }
    .sidebar-item.active {
      background: #1e1e28; color: #f4f4f5; border-left-color: #7c7cff; font-weight: 600;
    }
    .sidebar-item .si-name {
      flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .content-area { min-width: 0; }
    .tbadge {
      display: inline-block; padding: 1px 6px;
      border-radius: 10px; font-size: 10px; font-weight: 700; flex-shrink: 0;
    }
    .tbadge-pass { background: #14532d; color: #4ade80; }
    .tbadge-fail { background: #450a0a; color: #f87171; }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* ── result card ── */
    .section-title {
      font-size: 13px; font-weight: 600; color: #a1a1aa;
      text-transform: uppercase; letter-spacing: .08em; margin-bottom: 14px;
    }
    .result-card {
      background: #18181f; border: 1px solid #2a2a38;
      border-radius: 10px; margin-bottom: 14px; overflow: hidden;
    }
    .result-pass { border-left: 3px solid #4ade80; }
    .result-fail { border-left: 3px solid #f87171; }
    .result-header {
      display: flex; align-items: center; gap: 12px;
      padding: 14px 20px; background: #1e1e28; flex-wrap: wrap;
    }
    .trial-label { font-size: 11px; color: #6b6b80; text-transform: uppercase; letter-spacing: .06em; }
    .score-num { font-size: 20px; font-weight: 700; }
    .score-green { color: #4ade80; }
    .score-red   { color: #f87171; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; }
    .badge-pass { background: #14532d; color: #4ade80; }
    .badge-fail { background: #450a0a; color: #f87171; }
    .result-path { font-family: 'Cascadia Code','Consolas',monospace; font-size: 13px; color: #a1a1aa; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .diag-counts { font-size: 11px; display: flex; gap: 8px; flex-shrink: 0; }
    .cnt-error  { color: #f87171; }
    .cnt-warn   { color: #facc15; }
    .cnt-info   { color: #60a5fa; }
    .cnt-checks { color: #6b6b80; }

    /* ── check rows ── */
    .checks-list { padding: 0; }
    .check-row {
      display: grid; grid-template-columns: 28px 1fr auto;
      align-items: start; padding: 9px 20px;
      border-bottom: 1px solid #1a1a24; gap: 10px; font-size: 13px;
    }
    .check-row:last-child { border-bottom: none; }
    .check-pass { background: transparent; }
    .check-pass .check-icon { color: #4ade80; font-size: 14px; padding-top: 1px; }
    .check-pass .check-name { color: #a1a1aa; }
    .check-error   { background: #1c1010; border-left: 3px solid #f87171; }
    .check-error   .check-icon { color: #f87171; font-size: 14px; padding-top: 1px; }
    .check-error   .check-name { color: #f4f4f5; font-weight: 600; }
    .check-warning { background: #1a1800; border-left: 3px solid #facc15; }
    .check-warning .check-icon { color: #facc15; font-size: 14px; padding-top: 1px; }
    .check-warning .check-name { color: #f4f4f5; font-weight: 600; }
    .check-info    { background: #0e1320; border-left: 3px solid #60a5fa; }
    .check-info    .check-icon { color: #60a5fa; font-size: 14px; padding-top: 1px; }
    .check-info    .check-name { color: #f4f4f5; font-weight: 600; }
    .check-diags { grid-column: 1 / -1; margin-top: 4px; }
    .cbadge-pass    { background: #14532d; color: #4ade80; }
    .cbadge-error   { background: #450a0a; color: #f87171; }
    .cbadge-warning { background: #422006; color: #facc15; }
    .cbadge-info    { background: #0c2040; color: #60a5fa; }
    .cbadge-pass,.cbadge-error,.cbadge-warning,.cbadge-info {
      display: inline-block; padding: 1px 8px; border-radius: 4px;
      font-size: 10px; font-weight: 700; letter-spacing: .07em;
      text-transform: uppercase; white-space: nowrap; align-self: center;
    }

    /* ── inline diagnostics ── */
    .diag-row {
      display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px;
      padding: 8px 12px; margin: 4px 0; border-radius: 6px; font-size: 12px;
    }
    .sev-error { background: #1c1010; border-left: 3px solid #f87171; }
    .sev-warn  { background: #1a1800; border-left: 3px solid #facc15; }
    .sev-info  { background: #0e1320; border-left: 3px solid #60a5fa; }
    .sev-error .diag-sev { color: #f87171; }
    .sev-warn  .diag-sev { color: #facc15; }
    .sev-info  .diag-sev { color: #60a5fa; }
    .diag-sev  { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; flex-shrink: 0; }
    .diag-rule { font-family: 'Cascadia Code','Consolas',monospace; font-size: 11px; color: #7c7cff; flex-shrink: 0; }
    .diag-loc  { font-size: 11px; color: #6b6b80; font-family: 'Cascadia Code','Consolas',monospace; flex-shrink: 0; }
    .diag-msg  { color: #e4e4e7; flex: 1; min-width: 200px; line-height: 1.5; }
    .diag-context { width: 100%; font-size: 11px; color: #6b6b80; font-family: 'Cascadia Code','Consolas',monospace; padding: 2px 0; }

    .footer { margin-top: 40px; text-align: center; font-size: 11px; color: #3f3f52; }
"""

_HTML_TAB_JS = """
  function showTab(id) {
    document.querySelectorAll('.sidebar-summary-btn, .sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === id));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === id));
  }
"""


def _rule_label(name: str) -> str:
    label = name.removeprefix("check_").replace("_", " ")
    return label[:1].upper() + label[1:] if label else name


def _render_check_rows(r: ValidationResult) -> str:
    rows: list[str] = []
    for cr in r.check_runs:
        if cr.passed:
            rows.append(
                f'<div class="check-row check-pass">'
                f'<span class="check-icon">&#10003;</span>'
                f'<span class="check-name">{_rule_label(cr.name)}</span>'
                f'<span class="cbadge-pass">pass</span>'
                f'</div>'
            )
        else:
            worst = cr.worst_severity
            row_cls = f"check-{worst.value}" if worst else "check-info"
            badge_cls = f"cbadge-{worst.value}" if worst else "cbadge-info"
            icon = "&#10007;" if worst and worst.value == "error" else "&#9888;"
            diag_items = []
            for d in cr.diagnostics:
                d_cls = _SEV_HTML_CLASS.get(d.severity, "sev-info")
                d_lbl = _SEV_HTML_LABEL.get(d.severity, "info")
                loc = f"<span class='diag-loc'>line {d.line}</span>" if d.line is not None else ""
                ctx = f"<div class='diag-context'>{d.context}</div>" if d.context else ""
                diag_items.append(
                    f'<div class="diag-row {d_cls}">'
                    f'<span class="diag-sev">{d_lbl}</span>{loc}'
                    f'<span class="diag-rule">{d.rule}</span>'
                    f'<span class="diag-msg">{d.message}</span>{ctx}'
                    f'</div>'
                )
            rows.append(
                f'<div class="check-row {row_cls}">'
                f'<span class="check-icon">{icon}</span>'
                f'<span class="check-name">{_rule_label(cr.name)}</span>'
                f'<span class="{badge_cls}">{worst.value if worst else "info"}</span>'
                f'<div class="check-diags">{"".join(diag_items)}</div>'
                f'</div>'
            )
    return "".join(rows)


def _render_skill_card(r: ValidationResult, show_path: bool = True) -> str:
    status_cls = "result-pass" if r.valid else "result-fail"
    badge_cls = "badge-pass" if r.valid else "badge-fail"
    badge_txt = "PASS" if r.valid else "FAIL"
    score_val = "1.00" if r.valid else "0.00"
    score_cls = "score-green" if r.valid else "score-red"
    r_errors = sum(1 for d in r.diagnostics if d.severity == Severity.ERROR)
    r_warns  = sum(1 for d in r.diagnostics if d.severity == Severity.WARNING)
    r_infos  = sum(1 for d in r.diagnostics if d.severity == Severity.INFO)
    path_html = f'<span class="result-path" title="{r.path}">{r.path.name}</span>' if show_path else ""
    cnt_parts = []
    if r_errors: cnt_parts.append(f'<span class="cnt-error">{r_errors} error{"s" if r_errors != 1 else ""}</span>')
    if r_warns:  cnt_parts.append(f'<span class="cnt-warn">{r_warns} warning{"s" if r_warns != 1 else ""}</span>')
    if r_infos:  cnt_parts.append(f'<span class="cnt-info">{r_infos} info</span>')
    cnt_parts.append(f'<span class="cnt-checks">{len(r.check_runs)} checks</span>')
    return (
        f'<div class="result-card {status_cls}">'
        f'<div class="result-header">'
        f'<span class="type-tag type-tag-{r.file_type.value}">{r.file_type.value.capitalize()}</span>'
        f'<span class="{score_cls} score-num">{score_val}</span>'
        f'<span class="badge {badge_cls}">{badge_txt}</span>'
        f'{path_html}'
        f'<span class="diag-counts">{"".join(cnt_parts)}</span>'
        f'</div>'
        f'<div class="checks-list">{_render_check_rows(r)}</div>'
        f'</div>'
    )


def _render_summary_stats(results: list[ValidationResult], ts: str) -> str:
    passed  = sum(1 for r in results if r.valid)
    failed  = len(results) - passed
    total   = len(results)
    pass_rate = f"{100 * passed / total:.1f}%" if total else "N/A"
    err_cnt  = sum(1 for r in results for d in r.diagnostics if d.severity == Severity.ERROR)
    warn_cnt = sum(1 for r in results for d in r.diagnostics if d.severity == Severity.WARNING)
    info_cnt = sum(1 for r in results for d in r.diagnostics if d.severity == Severity.INFO)
    c_run    = sum(len(r.check_runs) for r in results)
    c_pass   = sum(1 for r in results for cr in r.check_runs if cr.passed)
    pr_cls   = "green" if not failed else "red"
    return f"""
    <div class="summary-grid">
      <div class="stat-card"><div class="stat-val {pr_cls}">{pass_rate}</div><div class="stat-label">Pass Rate</div></div>
      <div class="stat-card"><div class="stat-val blue">{total}</div><div class="stat-label">Files</div></div>
      <div class="stat-card"><div class="stat-val green">{passed}</div><div class="stat-label">Passed</div></div>
      <div class="stat-card"><div class="stat-val {'red' if failed else ''}">{failed}</div><div class="stat-label">Failed</div></div>
      <div class="stat-card"><div class="stat-val green">{c_pass}</div><div class="stat-label">Checks Passed</div></div>
      <div class="stat-card"><div class="stat-val blue">{c_run}</div><div class="stat-label">Checks Run</div></div>
      <div class="stat-card"><div class="stat-val {'red' if err_cnt else ''}">{err_cnt}</div><div class="stat-label">Errors</div></div>
      <div class="stat-card"><div class="stat-val {'yellow' if warn_cnt else ''}">{warn_cnt}</div><div class="stat-label">Warnings</div></div>
      <div class="stat-card"><div class="stat-val {'blue' if info_cnt else ''}">{info_cnt}</div><div class="stat-label">Info</div></div>
    </div>"""


def _render_skills_overview_table(results: list[ValidationResult]) -> str:
    rows = []
    for idx, r in enumerate(results):
        status_cls = "row-pass" if r.valid else "row-fail"
        badge_cls  = "badge-pass" if r.valid else "badge-fail"
        badge_txt  = "PASS" if r.valid else "FAIL"
        err  = sum(1 for d in r.diagnostics if d.severity == Severity.ERROR)
        warn = sum(1 for d in r.diagnostics if d.severity == Severity.WARNING)
        info = sum(1 for d in r.diagnostics if d.severity == Severity.INFO)
        cp   = sum(1 for cr in r.check_runs if cr.passed)
        ct   = len(r.check_runs)
        tab_id = f"tab-skill-{idx}"
        diag_html = " ".join(filter(None, [
            f'<span class="cnt-error">{err}E</span>' if err else "",
            f'<span class="cnt-warn">{warn}W</span>' if warn else "",
            f'<span class="cnt-info">{info}I</span>' if info else "",
            "" if (err or warn or info) else '<span style="color:#4ade80">clean</span>',
        ]))
        type_tag = f'<span class="type-tag type-tag-{r.file_type.value}">{r.file_type.value.capitalize()}</span>'
        display_name = r.path.stem if r.file_type == FileType.AGENT else r.path.parent.name
        rows.append(
            f'<tr class="{status_cls}" onclick="showTab(\'{tab_id}\')">'            f'<td>{type_tag}<a class="skill-name-link" onclick="event.stopPropagation();showTab(\'{tab_id}\');return false;" href="#">{display_name}</a></td>'
            f'<td><span class="badge {badge_cls}">{badge_txt}</span></td>'
            f'<td><span class="diag-counts">{diag_html}</span></td>'
            f'<td style="color:#a1a1aa">{cp}/{ct}</td>'
            f'</tr>'
        )
    return (
        '<table class="skills-table">'
        '<thead><tr><th>File</th><th>Status</th><th>Diagnostics</th><th>Checks</th></tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody>'
        '</table>'
    )


def _format_html(results: list[ValidationResult], version: str, target: Path) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    multi = len(results) > 1

    if multi:
        scan_type = "Plugin"
        scan_name = target.name
        body_html = _format_html_tabbed(results, target, ts)
    elif results[0].file_type == FileType.AGENT:
        scan_type = "Agent"
        scan_name = results[0].path.stem
        body_html = _format_html_single(results[0], target, ts, scan_type=scan_type)
    else:
        scan_type = "Skill"
        scan_name = results[0].path.parent.name
        body_html = _format_html_single(results[0], target, ts, scan_type=scan_type)

    page_title = f"AgentEval · {scan_type} Report · {scan_name}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{page_title}</title>
  <style>{_HTML_CSS}</style>
</head>
<body>
  <div class="topbar">
    <div class="brand">Agent<span>Eval</span></div>
    <div class="meta">v{version} &nbsp;·&nbsp; {ts}</div>
  </div>
  <div class="page">
    {body_html}
  </div>
  <div class="footer">Generated by AgentEval v{version} &nbsp;·&nbsp; {ts}</div>
  <script>{_HTML_TAB_JS}</script>
</body>
</html>
"""


def _format_html_single(r: ValidationResult, target: Path, ts: str, *, scan_type: str = "Skill") -> str:
    stats = _render_summary_stats([r], ts)
    card  = _render_skill_card(r, show_path=False)
    title_name = r.path.stem if r.file_type == FileType.AGENT else r.path.parent.name
    badge_extra = " scan-type-badge-agent" if r.file_type == FileType.AGENT else ""
    return f"""
    <div class="report-title"><span class="scan-type-badge{badge_extra}">{scan_type}</span>{title_name}</div>
    <div class="report-sub">{r.path}</div>
    {stats}
    <div class="section-title">Checks</div>
    {card}"""


def _format_html_tabbed(results: list[ValidationResult], target: Path, ts: str) -> str:
    plugin_name = target.name

    skills = [(idx, r) for idx, r in enumerate(results) if r.file_type == FileType.SKILL]
    agents = [(idx, r) for idx, r in enumerate(results) if r.file_type == FileType.AGENT]

    def _make_nav_item(idx: int, r: ValidationResult) -> str:
        name = r.path.stem if r.file_type == FileType.AGENT else r.path.parent.name
        b_cls = "tbadge-pass" if r.valid else "tbadge-fail"
        b_txt = "✓" if r.valid else "✗"
        return (
            f'<button class="sidebar-item" data-tab="tab-skill-{idx}" onclick="showTab(\'tab-skill-{idx}\')">'
            f'<span class="si-name">{name}</span>'
            f'<span class="tbadge {b_cls}">{b_txt}</span>'
            f'</button>'
        )

    # ── sidebar ──
    nav_parts: list[str] = [
        '<button class="sidebar-summary-btn active" data-tab="tab-summary" onclick="showTab(\'tab-summary\')">&#9776; Summary</button>'
    ]
    if skills:
        nav_parts.append('<div class="sidebar-section-lbl">Skills</div>')
        nav_parts.extend(_make_nav_item(idx, r) for idx, r in skills)
    if agents:
        nav_parts.append('<div class="sidebar-section-lbl">Agents</div>')
        nav_parts.extend(_make_nav_item(idx, r) for idx, r in agents)

    sidebar = f'<nav class="sidebar">{"".join(nav_parts)}</nav>'

    # ── summary panel ──
    stats = _render_summary_stats(results, ts)
    overview = _render_skills_overview_table(results)
    summary_panel = (
        f'<div id="tab-summary" class="tab-panel active">'
        f'{stats}'
        f'<div class="section-title">Files Overview</div>'
        f'{overview}'
        f'</div>'
    )

    # ── per-file panels ──
    skill_panels = []
    for idx, r in enumerate(results):
        card = _render_skill_card(r, show_path=False)
        panel_name = r.path.stem if r.file_type == FileType.AGENT else r.path.parent.name
        type_tag = f'<span class="type-tag type-tag-{r.file_type.value}">{r.file_type.value.capitalize()}</span>'
        skill_panels.append(
            f'<div id="tab-skill-{idx}" class="tab-panel">'
            f'<div class="section-title">{type_tag}{panel_name}</div>'
            f'{card}'
            f'</div>'
        )

    content = f'<div class="content-area">{summary_panel}{"".join(skill_panels)}</div>'

    return f"""
    <div class="report-title"><span class="scan-type-badge">Plugin</span>{plugin_name}</div>
    <div class="report-sub">{target}</div>
    <div class="plugin-layout">
      {sidebar}
      {content}
    </div>"""


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

_EPILOG = """\
examples:
  agenteval SKILL.md                        validate a single file
  agenteval skills/                          scan a directory recursively
  agenteval SKILL.md --format json           machine-readable output for CI
  agenteval SKILL.md --max-lines 800         override sizing thresholds
  agenteval SKILL.md --ignore frontmatter    suppress a rule category
  agenteval SKILL.md --min-desc-score 50     require minimum description quality
  agenteval SKILL.md --target-agent vscode   scope checks to VS Code
  agenteval SKILL.md --strict-vscode         treat VS Code issues as errors
  agenteval SKILL.md --skip-ref-check        skip file reference validation
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenteval",
        description="AgentEval: Cross-agent skill quality gate for SKILL.md files. Validates against the agentskills.io spec.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to a SKILL.md file or a directory to scan recursively.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=None,
        metavar="N",
        help="Override the line-count threshold (default: 500).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        metavar="N",
        help="Override the token-count threshold (default: 8000).",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        dest="ignore_prefixes",
        metavar="PREFIX",
        default=[],
        help="Suppress rules matching this prefix. Can be repeated.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable colored output.",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        default=False,
        help="Suppress all output. Only the exit code indicates result.",
    )
    parser.add_argument(
        "--skip-dirname-check",
        action="store_true",
        default=False,
        help="Skip directory-name matching check (useful for CI temp paths).",
    )
    parser.add_argument(
        "--skip-ref-check",
        action="store_true",
        default=False,
        help="Skip file reference validation (useful when referenced files are unavailable).",
    )
    parser.add_argument(
        "--min-desc-score",
        type=int,
        default=None,
        metavar="N",
        help="Minimum description quality score (0-100). Below this triggers a warning.",
    )
    parser.add_argument(
        "--target-agent",
        choices=["claude", "vscode", "all"],
        default="all",
        help="Scope compatibility checks to a specific agent (default: all).",
    )
    parser.add_argument(
        "--strict-vscode",
        action="store_true",
        default=False,
        help="Promote VS Code compatibility issues to errors.",
    )
    parser.add_argument(
        "--html",
        nargs="?",
        const=None,
        default=None,
        metavar="FILE",
        help="Write an HTML report to FILE (default: auto-named '<type>-<name>-report.html'). Omit the value to use the auto-generated name.",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        default=False,
        help="Disable automatic HTML report generation.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # Ensure UTF-8 output on Windows where the default encoding may be cp1252.
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if sys.stderr.encoding and sys.stderr.encoding.lower().replace("-", "") != "utf8":
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    parser = _build_parser()
    args = parser.parse_args()

    target: Path = args.path
    if not target.exists():
        print(f"Error: path not found: {target}", file=sys.stderr)
        sys.exit(2)

    paths = _collect_paths(target)
    if not paths:
        print(f"No SKILL.md or agent files found under: {target}", file=sys.stderr)
        sys.exit(2)

    results = [
        validate(
            p,
            max_lines=args.max_lines,
            max_tokens=args.max_tokens,
            ignore_prefixes=args.ignore_prefixes or None,
            skip_dirname_check=args.skip_dirname_check,
            skip_ref_check=args.skip_ref_check,
            min_desc_score=args.min_desc_score,
            strict_vscode=args.strict_vscode,
            target_agent=args.target_agent,
        )
        for p in paths
    ]

    if not args.quiet:
        if args.format == "json":
            print(_format_json(results, __version__))
        else:
            use_color = not args.no_color and sys.stdout.isatty()
            print(_format_text(results, color=use_color))

    if not args.no_html:
        if args.html:
            html_path = Path(args.html)
        else:
            # Auto-generate filename: <type>-<name>-report.html
            if target.is_file():
                r0 = results[0]
                scan_type = r0.file_type.value  # "skill" or "agent"
                scan_name = target.stem if r0.file_type == FileType.AGENT else target.parent.name
            elif len(results) > 1:
                scan_type, scan_name = "plugin", target.name
            else:
                scan_type, scan_name = "skill", target.name
            safe_name = scan_name.lower().replace(" ", "-")
            html_path = Path(f"{scan_type}-{safe_name}-report.html")
        html_path.write_text(
            _format_html(results, __version__, target),
            encoding="utf-8",
        )
        if not args.quiet:
            print(f"\nHTML report written to: {html_path.resolve()}")

    any_errors = any(not r.valid for r in results)
    sys.exit(1 if any_errors else 0)
