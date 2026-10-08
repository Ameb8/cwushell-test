"""Standalone HTML presentation of the shared execution evidence."""

from collections import Counter
from html import escape

from cwushell_test.evidence import CaseEvidence, Report
from cwushell_test.reporting import _case, _metadata_fields, _summary_values

_STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #243247;
  background: #f3f5f8; line-height: 1.5; }
body { margin: 0; }
main { max-width: 1150px; margin: auto; padding: 28px 20px 60px; }
h1 { margin-bottom: 8px; font-size: clamp(1.6rem, 4vw, 2.2rem); }
h2 { margin-top: 30px; }
p { margin: 12px 0; }
.muted { color: #536176; }
nav, .controls { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
a { color: #2457a6; }
nav a, button { border: 1px solid #becbdd; border-radius: 6px;
  background: white; padding: 7px 12px; font: inherit; }
.controls[hidden] { display: none; }
button { cursor: pointer; color: #243247; }
a:focus-visible, button:focus-visible, summary:focus-visible {
  outline: 3px solid #2457a6; outline-offset: 3px; }
details { background: white; border: 1px solid #ced7e3; border-radius: 8px;
  margin: 12px 0; }
summary { padding: 12px 16px; cursor: pointer; font-weight: 600;
  overflow-wrap: anywhere; }
summary:hover { background: #edf2fa; border-radius: 8px; }
details[open] > summary { border-bottom: 1px solid #e1e6ed; }
.content { padding: 8px 16px 16px; min-width: 0; }
.case { border-left: 4px solid #597caa; }
.labels { display: block; font-weight: 400; font-size: .85rem; color: #536176; }
.field { margin: 12px 0; }
.field strong { font-size: .9rem; }
pre { background: #f5f7fa; border: 1px solid #e1e6ed; border-radius: 5px;
  padding: 10px 12px; white-space: pre-wrap; overflow-wrap: anywhere;
  tab-size: 4; font-size: .9rem; }
.content > pre { max-height: 32rem; overflow: auto; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { text-align: left; vertical-align: top; padding: 9px;
  border-bottom: 1px solid #e1e6ed; min-width: 80px; overflow-wrap: anywhere; }
th { background: #edf2fa; }
@media (max-width: 600px) {
  main { padding: 16px 10px 40px; } .content { padding: 6px 10px 12px; }
}
@media print {
  :root { background: white; } main { max-width: none; padding: 0; }
  nav, .controls { display: none; } pre { overflow: visible; }
  .content > pre { max-height: none; }
}
"""

_SCRIPT = """
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
  for (let item = target; item; item = item.parentElement) {
    if (item.tagName === 'DETAILS') item.open = true;
  }
  target.scrollIntoView({block: 'start'});
}
window.addEventListener('hashchange', revealHash);
document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener('click', () => setTimeout(revealHash, 0));
});
revealHash();
let printState;
window.addEventListener('beforeprint', () => {
  printState = Array.from(allDetails(), item => item.open);
  allDetails().forEach(item => item.open = true);
});
window.addEventListener('afterprint', () => {
  allDetails().forEach((item, index) => item.open = printState[index]);
});
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
            closing + f"<details><summary>{escape(title)}</summary>"
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
        return f"<pre><code>{escape(value)}</code></pre>\n"

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


def _summary_table(cases: list[tuple[int, CaseEvidence]]) -> str:
    headings = (
        "Suite",
        "Case",
        "Description",
        "Observed execution labels",
        "Events",
        "Exit status",
        "Signal",
        "Fully dispatched / undispatched",
    )
    result = '<div class="table-scroll"><table><thead><tr>'
    result += "".join(f'<th scope="col">{heading}</th>' for heading in headings)
    result += "</tr></thead><tbody>"
    for index, case in cases:
        result += "<tr>"
        for column, value in enumerate(_summary_values(case)):
            content = escape(value)
            if column == 1:
                content = f'<a href="#case-{index}">{content}</a>'
            result += f"<td>{content}</td>"
        result += "</tr>"
    return result + "</tbody></table></div>\n"


def render_html_report(report: Report) -> str:
    """Render every recorded observation without external assets or dependencies."""
    result = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>CWUShell execution evidence</title>"
        f"<style>{_STYLE}</style></head><body><main>"
        '<h1>CWUShell execution evidence</h1><p class="muted">'
        "For manual review. Execution labels describe observations only. "
        "COMPLETED means execution completion only; it does not imply correct output. "
        "PROMPT means synchronization, EOF means terminal closure, PROCESS_EXIT "
        "means an observed exit status, and SIGNAL means an observed terminating signal. "
        "Multiple observations can coexist, including TIMEOUT and COMPLETED.</p>"
        f"<p><strong>{len(report.cases)} cases recorded</strong> · "
        "Expand a suite, case, or evidence section to inspect its details.</p>"
        '<div class="controls" hidden><button id="expand" type="button">Expand all</button>'
        '<button id="collapse" type="button">Collapse all</button></div>'
        '<details><summary>Execution metadata</summary><div class="content">'
    )
    renderer = HTMLRenderer()
    for label, value in _metadata_fields(report):
        result += renderer.field(label, value)
    result += "</div></details>"
    groups: dict[str, list[tuple[int, CaseEvidence]]] = {}
    for index, case in enumerate(report.cases, 1):
        groups.setdefault(case.suite_id, []).append((index, case))
    result += '<nav aria-label="Suites">'
    for index, suite_id in enumerate(groups, 1):
        result += f'<a href="#suite-{index}">{escape(suite_id)}</a>'
    result += "</nav><h2>Suite overview</h2>"
    if not groups:
        result += "<p>No cases recorded.</p>"
    for index, (suite_id, cases) in enumerate(groups.items(), 1):
        counts = Counter(label for _, case in cases for label in case.summary.outcomes)
        labels = "; ".join(f"{label}: {count}" for label, count in counts.items())
        result += (
            f'<details id="suite-{index}" class="suite"><summary>'
            f'{escape(suite_id)} · {len(cases)} cases<span class="labels">'
            f'{escape(labels)}</span></summary><div class="content">'
        )
        result += _summary_table(cases)
        for case_index, case in cases:
            labels = ", ".join(case.summary.outcomes)
            if case.session.truncated:
                labels += "; TRUNCATED"
            result += (
                f'<details id="case-{case_index}" class="case"><summary>'
                f'{escape(case.case_id)} · {escape(case.title)}<span class="labels">'
                f'{escape(labels)}</span></summary><div class="content">'
            )
            result += _case(case, case_index, HTMLRenderer())
            result += "</div></details>"
        result += "</div></details>"
    result += (
        '</main><script>document.querySelector(".controls").hidden = false;'
        f"{_SCRIPT}</script></body></html>\n"
    )
    return result
