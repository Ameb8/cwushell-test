"""HTML evidence preservation, disclosure structure, and inert target text."""

import re
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

import pytest

from cwushell_test.evidence import FileObservation, Fixture
from cwushell_test.html_reporting import render_html_report
from cwushell_test.pty_session import Evidence, Interaction
from cwushell_test.reporting import ReportWriteError, render_report, write_report
from tests.test_reporting import case_for, report_for


class ParsedReport(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.blocks: list[str] = []
        self.text: list[str] = []
        self.disclosure_depths: list[int] = []
        self.disclosures: list[dict[str, str | None]] = []
        self.links: list[str] = []
        self.ids: list[str] = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script":
            self.scripts += 1
        if "id" in attributes:
            self.ids.append(attributes["id"])
        if tag == "a":
            self.links.append(attributes.get("href", ""))
        if tag == "details":
            self.disclosure_depths.append(self.stack.count("details") + 1)
            self.disclosures.append(attributes)
        if tag == "code":
            self.blocks.append("")
        if tag not in ("meta", "br", "hr", "input"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag

    def handle_data(self, data):
        if "code" in self.stack:
            self.blocks[-1] += data
        if not any(tag in self.stack for tag in ("style", "script")):
            self.text.append(data)


def rich_case():
    hostile = '</code></pre><script>alert("evidence")</script>& café\n```\t  end'
    session = Evidence(
        256,
        raw_output=hostile.encode(),
        truncated=True,
        dispatched=["echo\talpha   beta"],
        undispatched=["exit"],
        interactions=[
            Interaction(None, "TIMEOUT", "cwushell>"),
            Interaction("echo\talpha   beta", "TIMEOUT", "cwushell>"),
        ],
        reason="TIMEOUT",
        exit_status=7,
        signal_status=11,
        cleanup_actions=["SIGTERM", "SIGKILL"],
        cleanup_signal_status=9,
        cleanup_error="cleanup diagnostic <&>",
        error="execution diagnostic <&>",
        working_directory="/tmp/session <&>",
    )
    return replace(
        case_for(session),
        title=hostile,
        fixtures=(Fixture("source<&>.txt", "file", b"initial\xff\n"),),
        controlled_environment={"TERM": "dumb", "MISSING": None},
        file_observations=(
            FileObservation(
                "source<&>.txt", "after", True, b"observed\xff\n", "diagnostic<&>"
            ),
        ),
        notes=("note <&>",),
    )


def test_html_preserves_markdown_evidence_and_escapes_target_markup():
    case = rich_case()
    report = report_for(case)
    document = render_html_report(report)
    parsed = ParsedReport()
    parsed.feed(document)
    assert parsed.stack == []
    assert parsed.scripts == 1  # Only the report's own navigation script.
    assert case.session.output in parsed.blocks
    assert case.title in "".join(parsed.text)
    # Every fenced metadata/evidence value from Markdown survives in HTML.
    markdown_blocks = re.findall(
        r"^(`{3,})text\n(.*?)^\1$", render_report(report), re.MULTILINE | re.DOTALL
    )
    html_blocks = {block.rstrip("\n") for block in parsed.blocks}
    assert markdown_blocks
    for _, block in markdown_blocks:
        assert block.rstrip("\n") in html_blocks
    text = "".join(parsed.text)
    for observation in (
        "TRUNCATED",
        "INCOMPLETE_DISPATCH",
        "TIMEOUT",
        "SIGNAL",
        "Prompt synchronization was not established",
        "startup fallback",
        "Configured raw-byte limit: 256",
        "Cleanup-phase statuses are separate",
    ):
        assert observation in text
    assert "&lt;script&gt;" in document
    assert "PASS" not in text and "FAIL" not in text


def test_suites_cases_sections_are_nested_closed_and_linkable():
    cases = tuple(
        replace(case_for(Evidence(64)), case_id=f"T{i}.one", suite_id=f"T{i}")
        for i in range(1, 7)
    )
    parsed = ParsedReport()
    parsed.feed(render_html_report(report_for(*cases)))
    assert parsed.stack == []
    assert max(parsed.disclosure_depths) == 3
    assert (
        len([item for item in parsed.disclosures if item.get("class") == "suite"]) == 6
    )
    assert (
        len([item for item in parsed.disclosures if item.get("class") == "case"]) == 6
    )
    assert all("open" not in item for item in parsed.disclosures)
    assert len(parsed.ids) == len(set(parsed.ids))
    assert all(link[1:] in parsed.ids for link in parsed.links)
    assert len(parsed.links) == 12


def test_empty_html_report():
    assert "No cases recorded." in render_html_report(report_for())


def test_html_writer_selected_path_and_utf8(tmp_path: Path):
    output = tmp_path / "selected evidence.custom"
    report = report_for(rich_case())
    assert write_report(report, output, "html") == output.resolve()
    assert output.read_bytes() == render_html_report(report).encode("utf-8")


def test_html_writer_error_names_format_and_path(tmp_path: Path):
    output = tmp_path / "missing" / "report.html"
    with pytest.raises(ReportWriteError, match="Cannot write HTML report") as error:
        write_report(report_for(), output, "html")
    assert str(output) in str(error.value)
