"""Two protocol questions one conformance run cannot ask.

`mcp_conformance` checks one revision -- whichever the client happened to
request -- and one provider's idea of a tool declaration. Neither is the
question a reader has when they have to interoperate.

The version matrix asks the handshake once per published revision. Its finding
is not "supported" or "unsupported": both are correct, and a server that answers
a revision it does not implement with one it does is doing what the spec asks.
The finding is a server that **echoes back whatever it was sent**, including a
revision that never existed. That server is agreeing rather than negotiating,
and the mismatch surfaces later as a field missing for no visible reason. It is
why an impossible version is in the list.

The equivalence report asks whether declaring a tool once means the same thing
to four providers. The comparison is on meaning rather than bytes: a dialect
that renames a key is equivalent, one that drops a constraint is not. An
equality check would report every dialect as different and tell nobody anything.
"""

from __future__ import annotations

import sys

import pytest
from tooltrace.agents.mcp import fake_server_command
from tooltrace.agents.mcp_versions import (
    CRASHED,
    DOWNGRADED,
    ECHOED_UNKNOWN,
    KNOWN_VERSIONS,
    NO_VERSION,
    render_markdown,
    version_matrix,
)
from tooltrace.agents.tool_equivalence import equivalence_report
from tooltrace.cli.main import main

#: Answers every handshake with the version it was handed. Not a hypothetical:
#: echoing the client's field is the shortest way to make a handshake "work".
ECHOING_SERVER = r"""
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    params = msg.get("params") or {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
        "protocolVersion": params.get("protocolVersion"),
        "capabilities": {}, "serverInfo": {"name": "echo", "version": "0"}}}) + "\x0a")
    sys.stdout.flush()
"""

#: Completes the handshake and never says which protocol it settled on.
SILENT_VERSION_SERVER = r"""
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
        "capabilities": {}, "serverInfo": {"name": "quiet", "version": "0"}}}) + "\x0a")
    sys.stdout.flush()
"""


def command_for(script: str) -> list[str]:
    return [sys.executable, "-c", script]


@pytest.fixture(scope="module")
def bundled() -> dict:
    return version_matrix(fake_server_command())


# --- the version matrix -----------------------------------------------------


def test_the_fixture_implements_one_revision_and_says_which(bundled: dict) -> None:
    assert bundled["supported"] == ["2024-11-05"]
    assert bundled["ok"] is True


def test_answering_a_newer_request_with_an_older_revision_is_correct(bundled: dict) -> None:
    """Downgrading is negotiation, not a defect, and must not be reported as one."""
    row = next(r for r in bundled["versions"] if r["sent"] == "2025-06-18")
    assert row["outcome"] == DOWNGRADED
    assert row["problem"] is False


def test_a_server_that_echoes_the_version_is_caught() -> None:
    report = version_matrix(command_for(ECHOING_SERVER))
    assert report["ok"] is False
    impossible = next(r for r in report["versions"] if r["sent"] == "9999-01-01")
    assert impossible["outcome"] == ECHOED_UNKNOWN
    assert impossible["problem"] is True


def test_an_echoing_server_still_looks_fine_on_real_versions() -> None:
    """Which is exactly why an impossible version has to be sent.

    Test only against published revisions and an echoing server passes every
    one of them.
    """
    report = version_matrix(command_for(ECHOING_SERVER), versions=KNOWN_VERSIONS)
    assert report["ok"] is True
    assert report["supported"] == sorted(KNOWN_VERSIONS)


def test_a_handshake_with_no_version_at_all_is_a_problem() -> None:
    report = version_matrix(command_for(SILENT_VERSION_SERVER))
    assert report["ok"] is False
    assert all(r["outcome"] == NO_VERSION for r in report["versions"])


def test_a_server_that_will_not_start_is_reported_not_raised() -> None:
    report = version_matrix(["definitely-not-a-real-binary-xyz"], versions=("2024-11-05",))
    assert report["versions"][0]["outcome"] == CRASHED
    assert report["ok"] is False


def test_the_rendering_explains_an_echo() -> None:
    rendered = render_markdown(version_matrix(command_for(ECHOING_SERVER)))
    assert "agreeing, not negotiating" in rendered


def test_a_clean_matrix_does_not_mention_echoing(bundled: dict) -> None:
    assert "agreeing, not negotiating" not in render_markdown(bundled)


def test_every_published_revision_is_tested(bundled: dict) -> None:
    sent = {r["sent"] for r in bundled["versions"]}
    assert set(KNOWN_VERSIONS) <= sent
    assert "9999-01-01" in sent, "without an impossible version this measures nothing"


def test_the_cli_passes_the_bundled_fixture(capsys) -> None:
    assert main(["mcp-versions", "--json"]) == 0
    capsys.readouterr()


def test_the_cli_fails_an_echoing_server(capsys) -> None:
    code = main(["mcp-versions", "--json", "--", *command_for(ECHOING_SERVER)])
    assert code != 0
    assert "mishandled" in capsys.readouterr().err


# --- cross-provider equivalence ---------------------------------------------


def test_three_dialects_preserve_every_declared_constraint() -> None:
    report = equivalence_report()
    for dialect in ("openai", "anthropic", "mcp"):
        assert report["dialects"][dialect]["lossless"], report["dialects"][dialect]["losses"]


def test_gemini_is_reported_as_lossy_with_the_constraint_named() -> None:
    """Not a failure: a provider that cannot express a union is a fact about it."""
    report = equivalence_report()
    assert report["dialects"]["gemini"]["lossless"] is False
    losses = report["dialects"]["gemini"]["losses"]
    assert any(loss["tool"] == "git" and "args.oneOf" in loss["dropped"] for loss in losses)
    assert report["ok"] is True, "a provider's limits are not this project's defect"


def test_a_renamed_key_does_not_count_as_a_loss() -> None:
    """Anthropic moves the schema to `input_schema`; nothing about it changed.

    A byte comparison would flag all four dialects and tell nobody anything.
    """
    report = equivalence_report(["read_file"])
    assert report["dialects"]["anthropic"]["lossless"]
    assert report["dialects"]["openai"]["lossless"]


def test_required_arguments_survive_every_dialect() -> None:
    report = equivalence_report()
    for dialect, result in report["dialects"].items():
        dropped = [d for loss in result["losses"] for d in loss["dropped"]]
        assert not any(d.endswith(".required") for d in dropped), (
            f"{dialect} drops a required-argument constraint, which changes what a model may send"
        )


def test_the_cli_reports_equivalence(capsys) -> None:
    assert main(["tools", "--equivalence", "--json"]) == 0
    capsys.readouterr()
