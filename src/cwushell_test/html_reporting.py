"""Standalone HTML presentation of the shared execution evidence."""

from html import escape
from signal import Signals

from cwushell_test.evidence import CaseEvidence, Report
from cwushell_test.reporting import _case, _metadata_fields

_STYLE = """
:root { font: 15px/1.55 system-ui, sans-serif; color: #202b36;
  background: #f5f6f8; color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; }
header { background: white; border-bottom: 1px solid #d9dfe6;
  padding: 22px max(24px, calc((100vw - 1280px)/2)); }
main { max-width: 1328px; padding: 0 24px 50px; margin: auto; }
h1 { font-size: 27px; line-height: 1.2; margin: 12px 0 8px; }
h2 { font-size: 20px; } h3 { font-size: 15px; }
p { margin: 6px 0 12px; }
.muted, .note, .count, .case-id { color: #576574; }
.note, .count, .review { font-size: 13px; }
.case-id { font: 12px/1.55 ui-monospace, monospace; }
.controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin: 20px 0; }
button, input, select { font: inherit; }
button, select, input[type=search] { border: 1px solid #b9c2cd;
  border-radius: 5px; background: white; color: inherit; padding: 7px 11px; }
button, summary { cursor: pointer; }
:focus-visible { outline: 3px solid #337bb7; outline-offset: 3px; }
.count { margin-left: auto; }
.review { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.review input { width: 16px; height: 16px; }
.table-scroll { overflow-x: auto; background: white;
  border: 1px solid #d5dde5; border-radius: 6px; }
.scan { border-collapse: collapse; width: 100%; table-layout: fixed; }
th { font-size: 12px; color: #576574; background: #f0f3f6; text-align: left; }
th, td { padding: 12px 16px; vertical-align: top; overflow-wrap: anywhere; }
tbody .scan-row > td { border-top: 1px solid #e0e5eb; padding-top: 16px; }
.title-cell { width: 22%; } .input-cell { width: 20%; }
.event-cell { width: 18%; } .output-cell { width: 40%; }
pre { margin: 0; font: 13px/1.65 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 4; background: #f6f8fa;
  padding: 10px; border: 1px solid #e0e5eb; border-radius: 4px; }
.output-cell pre { background: white; border: 0; padding: 0; }
.badge { display: inline-block; border: 1px solid #c5d1db; border-radius: 4px;
  padding: 2px 7px; font-size: 12px; font-weight: 600; background: #f1f5f8;
  color: #3a5265; margin: 0 5px 4px 0; }
.warn { background: #fff3d9; border-color: #e9ce91; color: #75500a; }
.danger { background: #fff0ef; border-color: #e5b8b3; color: #943329; }
.capture { color: #75500a; font-size: 12px; margin-top: 7px; }
.detail-row > td { padding-top: 0; }
summary { color: #245c94; padding: 5px 0; }
.case > summary { margin-left: 60%; font-size: 13px; }
.content { padding: 16px; min-width: 0; background: #f8fafc; }
.content details { margin-top: 12px; }
.content .content { background: white; }
.field { margin: 12px 0; } .field strong { font-size: 13px; }
.field pre { margin-top: 5px; }
.content > pre { max-height: 32rem; overflow: auto; }
[hidden] { display: none !important; }
@media (max-width: 800px) {
  header { padding: 20px; } main { padding: 0 16px 35px; }
  .scan { min-width: 840px; } .count { margin-left: 0; }
  .controls input[type=search] { width: 100%; }
}
@media print {
  :root { background: white; } header { padding: 10px; } main { padding: 0; }
  .controls, .review { display: none; } .scan { min-width: 0; }
  .table-scroll { overflow: visible; } .content > pre { max-height: none; }
}
"""

_SCRIPT = """
const rows = Array.from(document.querySelectorAll('tbody[data-case]'));
const search = document.getElementById('search');
const suite = document.getElementById('suite');
const mode = document.getElementById('events');
const count = document.getElementById('count');
// Cache text from every evidence section, including collapsed sections.
const evidence = rows.map(row => (row.textContent + row.dataset.inputs).toLowerCase());
function filterCases() {
  const query = search.value.toLowerCase();
  let matching = 0, reviewed = 0;
  rows.forEach((row, index) => {
    const inspected = row.querySelector('input[type=checkbox]').checked;
    reviewed += Number(inspected);
    const match = (!suite.value || row.dataset.suite === suite.value) &&
      (!query || evidence[index].includes(query)) &&
      (mode.value !== 'events' || row.dataset.alert === 'true') &&
      (mode.value !== 'unreviewed' || !inspected);
    row.hidden = !match;
    matching += Number(match);
  });
  count.textContent = `${matching} of ${rows.length} cases · ${reviewed} reviewed`;
  document.getElementById('empty').hidden = matching !== 0;
}
[search, suite, mode].forEach(control => control.addEventListener('input', filterCases));
rows.forEach(row => {
  const checkbox = row.querySelector('input[type=checkbox]');
  checkbox.checked = false;
  checkbox.addEventListener('change', () => {
    if (mode.value === 'unreviewed' && checkbox.checked) mode.focus();
    filterCases();
  });
});
const allDetails = () => document.querySelectorAll('details');
document.getElementById('expand').addEventListener('click', () => {
  allDetails().forEach(item => item.open = true);
});
document.getElementById('collapse').addEventListener('click', () => {
  allDetails().forEach(item => item.open = false);
});
function revealHash() {
  const target = document.getElementById(location.hash.slice(1));
  if (!target) return;
  search.value = ''; suite.value = ''; mode.value = 'all'; filterCases();
  for (let item = target; item; item = item.parentElement) {
    if (item.tagName === 'DETAILS') item.open = true;
  }
  target.scrollIntoView({block: 'start'});
}
window.addEventListener('hashchange', revealHash);
let printState;
window.addEventListener('beforeprint', () => {
  printState = Array.from(allDetails(), item => item.open);
  allDetails().forEach(item => item.open = true);
  rows.forEach(row => row.hidden = false);
});
window.addEventListener('afterprint', () => {
  allDetails().forEach((item, index) => item.open = printState[index]);
  filterCases();
});
document.querySelector('.controls').hidden = false;
document.querySelectorAll('.review').forEach(label => label.hidden = false);
filterCases();
revealHash();
"""


class HTMLRenderer:
    """Render case sections using native keyboard-accessible disclosures."""

    def __init__(self) -> None:
        self.section_open = False

    def start_case(self, index: int) -> str:
        return ""

    def section(self, title: str) -> str:
        closing = "</div></details>\n" if self.section_open else ""
        self.section_open = True
        return (
            closing + f"<details open><summary>{escape(title)}</summary>"
            '<div class="content">\n'
        )

    def text(self, value: str) -> str:
        return "".join(
            f"<p>{escape(paragraph)}</p>\n"
            for paragraph in value.strip().split("\n\n")
            if paragraph
        )

    def field(self, label: str, value: object) -> str:
        return (
            f'<div class="field"><strong>{escape(label)}</strong>'
            f"{self.block(str(value))}</div>\n"
        )

    def block(self, value: str) -> str:
        return f'<pre tabindex="0"><code>{escape(value)}</code></pre>\n'

    def commands(self, label: str, commands: list[str]) -> str:
        result = (
            f"<h4>{escape(label)}</h4>\n"
            if label == "Event input"
            else self.section(label)
        )
        if not commands:
            return result + "<p>None.</p>\n"
        result += self.text(
            r"Escaped input representation: actual tabs are shown as \t; "
            r"backslashes as \\. Multiple spaces are preserved. "
            "The helper appends one LF to each fully dispatched input line."
        )
        for index, command in enumerate(commands, 1):
            result += self.field(
                f"Input {index}", command.replace("\\", "\\\\").replace("\t", "\\t")
            )
        return result

    def finish_case(self) -> str:
        return "</div></details>\n" if self.section_open else ""


def _input_text(commands: list[str]) -> str:
    return "\n".join(
        command.replace("\\", "\\\\").replace("\t", "\\t") for command in commands
    )


def _badge(text: str, style: str = "") -> str:
    return f'<span class="badge {style}">{escape(text)}</span>'


def _preview(output: str) -> tuple[str, bool]:
    """Bound previews by both lines and characters, including single-line floods."""
    preview = "\n".join(output.split("\n")[:3])[:480]
    return preview, len(preview) < len(output)


def _scan_case(case: CaseEvidence, index: int) -> str:
    session = case.session
    summary = case.summary
    alert = "TIMEOUT" in summary.outcomes or session.signal_status is not None
    result = (
        f'<tbody data-case="{index}" data-suite="{escape(case.suite_id)}" '
        f'data-inputs="{escape(chr(10).join(command.text for command in case.commands))}" '
        f'data-alert="{str(alert).lower()}"><tr class="scan-row">'
        f'<td><div class="case-id">{escape(case.case_id)}</div>'
        f"<strong>{escape(case.title)}</strong>"
        f'<label class="review" hidden><input type="checkbox" autocomplete="off" '
        f'aria-label="Reviewed {escape(case.case_id)}"> Reviewed</label></td>'
        '<td class="input-cell">'
    )
    renderer = HTMLRenderer()
    result += (
        renderer.block(_input_text(session.dispatched))
        if session.dispatched
        else '<p class="note">No inputs fully dispatched.</p>'
    )
    if case.has_action_plan:
        result += '<p class="note">Interaction labels; exact action bytes and dispatch counts in full evidence.</p>'
    if session.undispatched:
        result += (
            '<p class="capture">Undispatched (may include a partially sent line):</p>'
        )
        result += renderer.block(_input_text(session.undispatched))
    result += '</td><td class="event-cell">'
    for label in summary.outcomes:
        style = (
            "danger"
            if label == "SIGNAL"
            else "warn"
            if label in ("TIMEOUT", "INCOMPLETE_DISPATCH", "CLEANUP_ERROR", "ERROR")
            else ""
        )
        result += _badge(label, style)
    if session.exit_status is not None:
        result += _badge(f"Observed exit {session.exit_status}")
    if session.signal_status is not None:
        try:
            name = Signals(session.signal_status).name
        except ValueError:
            name = "Unknown signal"
        result += _badge(
            f"Terminating signal {session.signal_status} · {name}", "danger"
        )
    for event in session.interactions:
        if event.reason == "TIMEOUT":
            phase = "Startup" if event.command is None else "Command"
            result += (
                f'<p class="capture">{phase} deadline expired waiting for '
                f"{escape(event.waiting_for)}.</p>"
            )
    result += f'<p class="note">{len(session.dispatched)} of {len(case.commands)} planned inputs fully dispatched.</p>'
    if session.truncated:
        result += _badge("Capture truncated · TRUNCATED", "warn")
        result += f'<p class="capture">Retained {len(session.raw_output)} raw bytes; limit {session.max_output_bytes}. Further output discarded.</p>'
    else:
        result += '<p class="note">Capture not truncated.</p>'
    preview, shortened = _preview(session.output)
    result += '</td><td class="output-cell">'
    result += (
        renderer.block(preview)
        if preview
        else '<p class="note">No terminal output retained.</p>'
    )
    if shortened:
        result += '<p class="note">Preview shortened — more captured output available in full evidence.</p>'
    if case.file_observations:
        result += '<p class="note">File observations available.</p>'
    result += (
        '</td></tr><tr class="detail-row"><td colspan="4">'
        f'<details id="case-{index}" class="case"><summary>'
        f'Read full evidence<span class="case-id"> · {escape(case.case_id)}</span>'
        '</summary><div class="content">'
    )
    result += _case(case, index, HTMLRenderer())
    return result + "</div></details></td></tr></tbody>\n"


def render_html_report(report: Report) -> str:
    """Render ordered scan rows and full evidence without external dependencies."""
    result = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>CWUShell execution evidence</title>"
        f"<style>{_STYLE}</style></head><body><header>"
        '<h1>CWUShell report <span class="muted">/ Scan table</span></h1>'
        "<p>Scan inputs, execution observations, and terminal output. Read full evidence for each case.</p>"
        '<p class="note">For manual review. COMPLETED means execution completion only; '
        "it does not imply correct output. PROMPT means synchronization, EOF means "
        "terminal closure. Intentional exits and printed diagnostics must be read "
        "in the context of the case inputs. Multiple observations can coexist.</p>"
        f'<p class="note">{len(report.cases)} cases recorded · Target: {escape(str(report.metadata.target))}</p>'
        '</header><main><details><summary>Execution metadata</summary><div class="content">'
    )
    renderer = HTMLRenderer()
    for label, value in _metadata_fields(report):
        result += renderer.field(label, value)
    result += (
        '</div></details><p class="note">Inputs use an escaped representation: '
        r"actual tabs appear as <code>\t</code>, literal backslashes as <code>\\</code>. "
        "Spaces are preserved. Line commands append one LF; action plans use explicit Enter. "
        "Terminal output is combined stdout + stderr evidence.</p>"
        '<p class="note">Reviewed means inspected by the reviewer; it assigns no '
        "correctness status or grade. Review progress resets on reload.</p>"
        '<div class="controls" hidden><label for="search">Find</label>'
        '<input id="search" type="search" placeholder="Case, input, or evidence…">'
        '<label for="suite">Suite</label><select id="suite"><option value="">All suites</option>'
    )
    for suite_id in dict.fromkeys(case.suite_id for case in report.cases):
        result += f'<option value="{escape(suite_id)}">{escape(suite_id)}</option>'
    result += (
        '</select><label for="events">Show</label><select id="events">'
        '<option value="all">All cases</option><option value="events">Timeouts / signals</option>'
        '<option value="unreviewed">Unreviewed</option></select>'
        '<button id="expand" type="button">Expand all</button>'
        '<button id="collapse" type="button">Collapse all</button>'
        '<span id="count" class="count" role="status" aria-live="polite"></span></div>'
        "<noscript><p>All cases and evidence are available below. Enable JavaScript "
        "for search, filters, and review tracking.</p></noscript>"
        '<p id="empty" hidden>No cases match these filters.</p>'
        '<div class="table-scroll" role="region" aria-label="Case evidence table" tabindex="0">'
        '<table class="scan"><thead><tr><th scope="col" class="title-cell">Test case</th>'
        '<th scope="col" class="input-cell">Dispatched input</th>'
        '<th scope="col" class="event-cell">Execution observations</th>'
        '<th scope="col" class="output-cell">Terminal output preview · stdout + stderr</th>'
        "</tr></thead>"
    )
    for index, case in enumerate(report.cases, 1):
        result += _scan_case(case, index)
    result += "</table></div>"
    if not report.cases:
        result += "<p>No cases recorded.</p>"
    return result + f"</main><script>{_SCRIPT}</script></body></html>\n"
