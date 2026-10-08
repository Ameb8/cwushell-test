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
        self.rows: list[dict[str, str | None]] = []
        self.scan_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tbody":
            self.rows.append(attributes)
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
        if "tr" in self.stack and "details" not in self.stack:
            self.scan_text.append(data)
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


def test_scan_table_preserves_report_order_with_native_full_evidence_controls():
    # Deliberately interleave suites: the renderer must preserve report order.
    cases = tuple(
        replace(case_for(Evidence(64)), case_id=f"T{i}.one", suite_id=f"T{i}")
        for i in (6, 1, 3, 2, 5, 4)
    )
    parsed = ParsedReport()
    parsed.feed(render_html_report(report_for(*cases)))
    assert parsed.stack == []
    assert [row["data-suite"] for row in parsed.rows] == [c.suite_id for c in cases]
    assert [row["data-case"] for row in parsed.rows] == [str(i) for i in range(1, 7)]
    assert max(parsed.disclosure_depths) == 2
    disclosures = [item for item in parsed.disclosures if item.get("class") == "case"]
    assert [item["id"] for item in disclosures] == [f"case-{i}" for i in range(1, 7)]
    assert all("open" not in item for item in disclosures)
    assert len(parsed.ids) == len(set(parsed.ids))
    assert "Read full evidence" in "".join(parsed.text)


@pytest.mark.parametrize(
    ("output", "shortened"),
    [
        ("one\ntwo\nthree", False),
        ("one\ntwo\nthree\nfour", True),
        ("x" * 481, True),
        ("x" * 480, False),
        ("", False),
    ],
)
def test_preview_shortening_does_not_claim_capture_truncation(output, shortened):
    session = Evidence(4096, raw_output=output.encode())
    parsed = ParsedReport()
    parsed.feed(render_html_report(report_for(case_for(session))))
    visible = "".join(parsed.scan_text)
    assert ("Preview shortened" in visible) == shortened
    assert "Capture not truncated." in visible
    assert "Capture truncated" not in visible
    assert session.output in parsed.blocks


def test_scan_row_labels_real_dispatch_capture_exit_and_signal_evidence():
    from cwushell_test.pty_session import Command

    case = replace(
        rich_case(), commands=(Command("echo\talpha   beta"), Command(r"exit\t42"))
    )
    parsed = ParsedReport()
    parsed.feed(render_html_report(report_for(case)))
    visible = "".join(parsed.scan_text)
    for text in (
        r"echo\talpha   beta",
        "Undispatched",
        "exit",
        "INCOMPLETE_DISPATCH",
        "1 of 2 planned inputs",
        "TIMEOUT",
        "Startup deadline expired",
        "Observed exit 7",
        "Terminating signal 11 · SIGSEGV",
        "Capture truncated",
        "Retained",
        "limit 256",
        "File observations available",
    ):
        assert text in visible
    assert parsed.rows[0]["data-alert"] == "true"
    assert parsed.rows[0]["data-inputs"] == "echo\talpha   beta\nexit\\t42"
    # Literal backslash+t must remain distinct from an actual tab.
    assert r"exit\\t42" in parsed.blocks


@pytest.mark.parametrize(
    ("session", "alert"),
    [
        (Evidence(64, reason="TIMEOUT"), "true"),
        (Evidence(64, signal_status=11), "true"),
        (Evidence(64, cleanup_signal_status=9), "false"),
        (Evidence(64, exit_status=42), "false"),
        (
            Evidence(
                64,
                interactions=[Interaction(None, "TIMEOUT", "cwushell>")],
                reason="COMPLETED",
            ),
            "true",
        ),
    ],
)
def test_timeout_signal_filter_uses_execution_observations_only(session, alert):
    parsed = ParsedReport()
    parsed.feed(render_html_report(report_for(case_for(session))))
    assert parsed.rows[0]["data-alert"] == alert


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
