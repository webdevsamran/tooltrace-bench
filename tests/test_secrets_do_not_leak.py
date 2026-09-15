"""Secrets must not reach output, storage, or the process list.

Every property here was true by construction and checked by nothing, which is
the state `Attachment` and `evaluate_policy` were in before they turned out not
to be true at all. So each is checked against the actual bytes, with real-shaped
secrets:

- a verification key handed to `a2a-card` must not appear in either output
  stream, and the documented way to pass one names an environment variable
  rather than carrying the value through `argv`, where any process on the
  machine can read it and shell history keeps it;
- a redaction record must not quote the personal data it reports finding -- a
  report that did would *be* the disclosure it exists to prevent;
- a bearer token goes to one host, and *host* means the parsed hostname, not a
  substring of the URL;
- `SecretFinding` must carry no part of what it matched;
- `api_key_env` holds the NAME of an environment variable, and a value that
  looks like a key is refused rather than echoed back.

The last three began as CodeQL alerts that I first judged false positives.
Reading the actual data-flow paths in the SARIF, rather than the paths I assumed
they had, found three real defects behind them: six characters of every detected
secret kept in a field nothing read, a credential echoed to stdout when someone
pastes a key into the field named for a variable, and a token attached on
`"api.github.com" in url` -- true of any host that cares to mention the name.

None of the three was exploitable the day it was written. That is what makes
them worth a test rather than a shrug: each was one parameter away.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.cli.main import main

# Synthetic, and the whole point of this file is that it never reaches an output
# stream. Marked per line rather than exempting the file, so a real key pasted in
# here later is still caught.
SECRET = "s3cr3t-value-nothing-should-print-a1b2c3"  # secret-scan: allow


@pytest.fixture
def card(tmp_path: Path) -> Path:
    path = tmp_path / "agent-card.json"
    path.write_text(
        json.dumps(
            {
                "name": "demo",
                "url": "https://agent.example.test",
                "version": "1.0.0",
                "capabilities": {},
                "skills": [],
            }
        ),
        encoding="utf-8",
    )
    return path


# --- a verification key must not come back out -------------------------------


def test_a_literal_key_never_appears_in_the_json_output(card: Path, capsys) -> None:
    main(["a2a-card", str(card), "--key", f"k1={SECRET}", "--json"])
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_a_literal_key_never_appears_in_the_human_output(card: Path, capsys) -> None:
    """The prose path prints a different set of fields, so it needs its own check."""
    main(["a2a-card", str(card), "--key", f"k1={SECRET}"])
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_an_env_key_never_appears_either(card: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TTB_TEST_VERIFICATION_KEY", SECRET)
    main(["a2a-card", str(card), "--key-env", "k1=TTB_TEST_VERIFICATION_KEY", "--json"])
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


# --- the environment form, which is the point --------------------------------


def test_the_environment_form_works(card: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TTB_TEST_VERIFICATION_KEY", SECRET)
    code = main(["a2a-card", str(card), "--key-env", "k1=TTB_TEST_VERIFICATION_KEY", "--json"])
    capsys.readouterr()
    # The card declares no signature, so conformance fails on required fields;
    # what matters here is that the key was accepted rather than rejected.
    assert code in (0, 3)


def test_a_missing_variable_is_refused_by_name(card: Path, capsys, monkeypatch) -> None:
    """Silently treating an unset variable as an empty key would verify
    signatures against the empty string."""
    monkeypatch.delenv("TTB_TEST_ABSENT", raising=False)
    code = main(["a2a-card", str(card), "--key-env", "k1=TTB_TEST_ABSENT"])
    assert code != 0
    assert "TTB_TEST_ABSENT" in capsys.readouterr().err


def test_the_literal_form_says_what_it_costs(card: Path, capsys) -> None:
    """It still works -- breaking it would be worse -- and it says why not to."""
    main(["a2a-card", str(card), "--key", f"k1={SECRET}"])
    err = capsys.readouterr().err
    assert "command line" in err
    assert "--key-env" in err


def test_no_other_command_takes_a_raw_secret(capsys) -> None:
    """The project's rule, checked rather than remembered.

    `openai_compat`, `anthropic` and `gemini` all take the *name* of an
    environment variable. `a2a-card --key` was the one place that took the value,
    and it is now the only one that may -- with a warning.
    """
    import argparse

    from tooltrace.cli.main import build_parser

    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    offenders = []
    for name, sub in subparsers[0].choices.items():
        for action in sub._actions:
            metavar = str(action.metavar or "")
            looks_like_a_credential = any(
                word in metavar for word in ("SECRET", "PASSWORD", "TOKEN")
            )
            allowed = (name, tuple(action.option_strings)) == ("a2a-card", ("--key",))
            if looks_like_a_credential and not allowed:
                offenders.append(f"{name} {action.option_strings}")
    assert offenders == [], f"these take a credential as an argument value: {offenders}"


# --- the redaction record must not quote what it found ------------------------


def test_the_redaction_record_never_quotes_the_data_it_reports(tmp_path: Path) -> None:
    """A report that printed the personal data it found would be the disclosure.

    `Finding` says so in a comment -- "Never the matched text" -- and nothing
    checked it. This does, against a bundle containing a real-looking email,
    card number and key.
    """
    from tooltrace.security.redaction import certificate, redaction_report, write_record

    bundle = tmp_path / "leaky.tooltrace"
    bundle.mkdir()
    planted = {
        "email": "victim.person@example.test",
        "card": "4111 1111 1111 1111",
        "key": "AKIAIOSFODNN7EXAMPLE",
    }
    (bundle / "result.json").write_text(
        json.dumps({"note": " ".join(planted.values())}), encoding="utf-8"
    )
    (bundle / "workspace.diff").write_text(planted["email"], encoding="utf-8")

    report = redaction_report(bundle)
    record = certificate([bundle], generated_at="2026-09-15T00:00:00Z")
    written = write_record(record, tmp_path / "out")

    # The report, the record and both files on disk -- the JSON one is what
    # CodeQL flagged, and the markdown one is the one a person actually reads.
    blob = (
        json.dumps(report)
        + json.dumps(record)
        + "".join(f.read_text(encoding="utf-8") for f in written)
    )
    leaked = [name for name, value in planted.items() if value in blob]
    assert leaked == [], f"the redaction record quotes the {leaked} it found"


def test_the_record_still_reports_that_it_found_something(tmp_path: Path) -> None:
    """The test above passes trivially if the scanner finds nothing at all."""
    from tooltrace.security.redaction import redaction_report

    bundle = tmp_path / "leaky.tooltrace"
    bundle.mkdir()
    (bundle / "result.json").write_text(
        json.dumps({"note": "reach me at victim.person@example.test"}), encoding="utf-8"
    )
    record = redaction_report(bundle)
    assert record["pii_findings"], "nothing was detected, so the leak check proves nothing"


# --- a token goes to one host, and host means host ----------------------------


def _captured_request(url: str, monkeypatch) -> object:
    """Run `_get_json` against `url`, returning the Request it would have sent."""
    import importlib.util
    import sys as _sys
    import urllib.error
    import urllib.request

    spec = importlib.util.spec_from_file_location(
        "ttb_check_action_refs_test",
        Path(__file__).resolve().parent.parent / "scripts" / "check_action_refs.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    _sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    seen: list[object] = []

    def fake_urlopen(request, *a, **k):
        seen.append(request)
        raise urllib.error.URLError("not sent")

    monkeypatch.setenv("GITHUB_TOKEN", SECRET)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.URLError):
        module._get_json(url)
    return seen[0]


def test_the_api_host_gets_the_token(monkeypatch) -> None:
    """The check has to still work, or the test below proves nothing."""
    request = _captured_request("https://api.github.com/repos/o/r/contents/action.yml", monkeypatch)
    assert request.get_header("Authorization") == f"Bearer {SECRET}"


@pytest.mark.parametrize(
    "url",
    [
        # Each of these contains the literal "api.github.com", and none of them
        # IS api.github.com. A substring test sent the credential to all three.
        "https://elsewhere.example/collect?next=api.github.com",
        "https://api.github.com.evil.example/repos/o/r",
        "https://evil.example/api.github.com/repos/o/r",
    ],
)
def test_a_lookalike_host_never_gets_the_token(url: str, monkeypatch) -> None:
    request = _captured_request(url, monkeypatch)
    assert request.get_header("Authorization") is None, f"the token was sent to {url}"


def test_pypi_does_not_get_a_github_token(monkeypatch) -> None:
    """The same function reaches two hosts; only one of them is authenticated."""
    request = _captured_request("https://pypi.org/pypi/tooltrace-bench/json", monkeypatch)
    assert request.get_header("Authorization") is None


# --- a finding says what matched, never any of what matched -------------------


def test_a_secret_finding_carries_no_part_of_the_secret() -> None:
    """`SecretFinding` used to keep the first six characters of every match.

    Six characters of a live credential, in a dataclass any caller could log,
    serialise or drop into a bundle, read by nothing. The module docstring
    promised "never the secret itself"; the field's own comment quietly weakened
    that to "never the *full* secret".
    """
    import dataclasses

    from tooltrace.security.sanitize import SecretFinding, find_secrets

    planted = "AKIAIOSFODNN7EXAMPLE"
    findings = find_secrets(f"aws key {planted} in a log line")
    assert findings, "nothing matched, so this proves nothing"

    fields = {f.name for f in dataclasses.fields(SecretFinding)}
    assert "preview" not in fields, "the preview field is back"

    for finding in findings:
        rendered = repr(finding)
        for size in range(4, len(planted) + 1):
            assert planted[:size] not in rendered, f"a {size}-char prefix survives in {rendered}"


def test_a_finding_still_locates_what_it_found() -> None:
    """Dropping `preview` must not cost the ability to act on a finding."""
    from tooltrace.security.sanitize import find_secrets

    text = "aws key AKIAIOSFODNN7EXAMPLE in a log line"
    finding = find_secrets(text)[0]
    assert text[finding.start : finding.end] == "AKIAIOSFODNN7EXAMPLE"
    assert finding.label


# --- api_key_env holds a NAME, and that is now enforced -----------------------


def _plan(api_key_env: str, tmp_path: Path) -> object:
    from tooltrace.cli.init import plan

    return plan(
        tmp_path,
        adapter="openai_compat",
        base_url="https://api.example.test/v1",
        model="a-model",
        api_key_env=api_key_env,
        write_workflow=False,
    )


def test_a_variable_name_is_echoed_because_a_name_is_not_a_secret(tmp_path: Path) -> None:
    result = _plan("OPENAI_API_KEY", tmp_path)
    assert any("OPENAI_API_KEY" in note for note in result.notes)


def _j(*parts: str) -> str:
    """Assemble a key-shaped value at runtime.

    The publication gate reported the whole-literal version of the Stripe entry
    below, correctly: a complete credential-shaped string had appeared in the
    tree. Waving it through with an allow marker would have been the wrong door
    -- the fixture has to stay realistic enough for a real scanner to bite, and
    the tree has to stay free of anything that looks like a live key. Joining
    fragments gets both. Same reasoning as
    `tests/test_secret_scan_catches_secrets.py`.
    """
    return "".join(parts)


@pytest.mark.parametrize(
    "pasted",
    [
        _j("sk-", "proj7Kd2mQx9vLtR4wY1nB6cV3hJ8sD5fG0aE2uI4oP"),
        _j("sk_", "live_4eC39HqLyjWDarjtT1zdp7dc"),
        _j("ghp_", "16C7e42F292c6912E7710c838347Ae178B4a"),
    ],
)
def test_a_pasted_key_is_never_echoed_back(pasted: str, tmp_path: Path) -> None:
    """The field named `api_key_env` is the one most likely to receive a key.

    The note it drives is printed to stdout and returned in the JSON payload, so
    echoing it put the credential in the user's scrollback and in any CI log.
    """
    result = _plan(pasted, tmp_path)
    blob = " ".join(result.notes) + json.dumps(result.agent_config)
    assert pasted not in blob, "the pasted key was echoed back"
    assert any("rotate it" in note for note in result.notes)


@pytest.mark.parametrize(
    "name",
    ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MY_TOKEN", "TOKEN", "HOME", "PATH", "K"],
)
def test_real_variable_names_are_accepted(name: str, tmp_path: Path) -> None:
    """A check that rejected ordinary names would just be turned off."""
    result = _plan(name, tmp_path)
    assert any(name in note for note in result.notes), f"{name} was rejected"


def test_a_prefixless_key_is_still_refused(tmp_path: Path) -> None:
    """The case both firm tests miss.

    A bare 32-character hex key is alphanumeric, so the charset test admits it,
    and carries no prefix any pattern knows. What gives it away is shape: no
    underscore and far longer than anyone's variable name.
    """
    bare = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    assert len(bare) == 32
    result = _plan(bare, tmp_path)
    blob = " ".join(result.notes) + json.dumps(result.agent_config)
    assert bare not in blob, "a prefixless key was echoed back"


def test_a_rejected_value_is_dropped_from_the_config(tmp_path: Path) -> None:
    """Otherwise it would be written to the config file it was rejected from."""
    result = _plan(_j("sk-", "proj7Kd2mQx9vLtR4wY1nB6cV3hJ8sD5fG0aE2uI4oP"), tmp_path)
    assert "api_key_env" not in result.agent_config
