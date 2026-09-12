"""The console's data has to come from the server, not from a fixture.

Every workspace page in `web/` rendered a `DEMO_*` constant, and rendered it
**whether or not a server was connected**. An administrator who pointed the
console at a real deployment saw an invented user list, an invented approval
queue, and three invented workers with invented utilisation rings -- with the
DEMO badge suppressed, because the badge was the one thing gated on
`isServerMode()`. `web/src/pages/workspace/shared.tsx` opens with the comment
"demo rows never leak into data". They leaked.

The reason was on this side: the state existed and nothing could ask for it.
There were four routes in total, none of them a list of anything except
experiments.

These tests are about that class of defect rather than about serialisation:

- **workspace scoping**, because the failure mode of a multi-tenant read
  endpoint is showing one customer another customer's rows;
- **authentication**, because an endpoint that answers an anonymous caller is a
  public one whatever the documentation says;
- **the secret stays behind**, for webhooks: the signing secret is the only
  thing that makes a delivery verifiable, and a read endpoint that returned it
  would hand every viewer the ability to forge one;
- **an empty answer says why**. There is no baseline store in this process, so
  the endpoint returns `[]` and a reason. A fabricated row would look the same
  to the dashboard and be a lie.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.server.core import (
    ROUTES,
    STATE,
    QuotaTracker,
    User,
    WebhookDispatcher,
    WorkspacePolicy,
)

READ_ENDPOINTS = (
    "/api/v1/users",
    "/api/v1/approvals",
    "/api/v1/audit",
    "/api/v1/policies",
    "/api/v1/webhooks",
    "/api/v1/workers",
    "/api/v1/baselines",
)


def call(path: str, user: User | None, body: dict | None = None) -> tuple[int, dict]:
    """Invoke a route the way the HTTP handler does, without a socket."""
    handler = ROUTES[("GET", path)]
    status, payload = handler(body or {}, user)
    return status, payload


def make_user(role: str = "admin", ws: str = "ws1", uid: str = "alice") -> User:
    return User(user_id=uid, display_name=uid, role=role, workspace_id=ws)


@pytest.fixture(autouse=True)
def _clean_state():
    """The server state is a module-level singleton.

    Left dirty, one test's users become another's, and the workspace-scoping
    assertions below would pass for the wrong reason.
    """
    before = (
        dict(STATE.users),
        dict(STATE.approvals.requests),
        dict(STATE.policies),
        dict(STATE.quotas),
        STATE.webhooks,
    )
    STATE.users.clear()
    STATE.approvals.requests.clear()
    STATE.policies.clear()
    STATE.quotas.clear()
    STATE.webhooks = None
    yield
    STATE.users.clear()
    STATE.users.update(before[0])
    STATE.approvals.requests.clear()
    STATE.approvals.requests.update(before[1])
    STATE.policies.clear()
    STATE.policies.update(before[2])
    STATE.quotas.clear()
    STATE.quotas.update(before[3])
    STATE.webhooks = before[4]


# --- they exist at all -------------------------------------------------------


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_the_endpoint_is_registered(path: str) -> None:
    """The console cannot fetch what the server does not route."""
    assert ("GET", path) in ROUTES, path


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_an_anonymous_caller_gets_nothing(path: str) -> None:
    """An endpoint that answers `None` is public, whatever the docs say."""
    status, payload = call(path, None)
    assert status == 401, (path, status, payload)


# --- users -------------------------------------------------------------------


def test_users_are_scoped_to_the_callers_workspace() -> None:
    STATE.users["alice"] = make_user(uid="alice", ws="ws1")
    STATE.users["bob"] = make_user(uid="bob", ws="ws2")
    status, payload = call("/api/v1/users", make_user(ws="ws1"))
    assert status == 200
    assert [u["user_id"] for u in payload["users"]] == ["alice"]


def test_a_service_account_is_labelled_as_one() -> None:
    """A token acting on its own is not a person, and an admin reviewing
    membership needs to see which is which."""
    STATE.users["ci"] = make_user(role="service_account", uid="ci", ws="ws1")
    _status, payload = call("/api/v1/users", make_user(ws="ws1"))
    assert payload["users"][0]["kind"] == "service_account"


# --- approvals ---------------------------------------------------------------


def test_approvals_are_scoped_and_listable() -> None:
    requester = make_user(role="runner", uid="rick", ws="ws1")
    STATE.approvals.request(
        request_id="apr-1",
        workspace_id="ws1",
        action="publish",
        payload={},
        requester=requester,
    )
    STATE.approvals.request(
        request_id="apr-2",
        workspace_id="ws2",
        action="publish",
        payload={},
        requester=make_user(role="runner", uid="rick", ws="ws2"),
    )
    _status, payload = call("/api/v1/approvals", make_user(ws="ws1"))
    assert [a["request_id"] for a in payload["approvals"]] == ["apr-1"]


# --- audit -------------------------------------------------------------------


def test_the_audit_view_says_whether_the_chain_still_verifies() -> None:
    """Entries without the verdict are a list of claims.

    The hash chain is the only reason to prefer this to a text file, so the
    answer to "is it intact" travels with the rows rather than being a second
    call somebody forgets to make.
    """
    STATE.audit.append(actor="alice", action="experiment.create", target="exp-1")
    status, payload = call("/api/v1/audit", make_user(role="admin"))
    assert status == 200
    assert payload["chain_verified"] is True
    assert payload["entries"], "the entry just appended is not in the list"


def test_the_audit_log_is_newest_first() -> None:
    """A reader opening an audit view wants what just happened."""
    STATE.audit.append(actor="a", action="first", target="t")
    STATE.audit.append(actor="a", action="second", target="t")
    _status, payload = call("/api/v1/audit", make_user(role="admin"))
    assert payload["entries"][0]["action"] == "second"


def test_a_viewer_cannot_read_the_audit_log() -> None:
    """Who did what is evidence, and a viewer's role does not carry it."""
    status, _payload = call("/api/v1/audit", make_user(role="viewer"))
    assert status == 403


def test_an_auditor_can() -> None:
    """The role exists precisely so a read-only outsider can see this."""
    status, _payload = call("/api/v1/audit", make_user(role="auditor"))
    assert status == 200


def test_the_returned_entries_cannot_be_used_to_rewrite_the_chain() -> None:
    """A caller handed the live dicts could mutate the log in place."""
    STATE.audit.append(actor="a", action="x", target="t")
    _status, payload = call("/api/v1/audit", make_user(role="admin"))
    payload["entries"][0]["actor"] = "mallory"
    _status, again = call("/api/v1/audit", make_user(role="admin"))
    assert again["entries"][0]["actor"] == "a"


# --- policies ----------------------------------------------------------------


def test_policy_and_quota_come_back_together() -> None:
    # `WorkspacePolicy` carries no workspace id of its own -- it is the value in
    # a dict keyed by one -- so the id is reported alongside rather than inside,
    # and the console has both without a second call.
    STATE.policies["ws1"] = WorkspacePolicy(network_modes=["offline"], max_runs_per_day=25)
    STATE.quotas["ws1"] = QuotaTracker({"runs": 10})
    STATE.quotas["ws1"].consume("runs", 3)
    _status, payload = call("/api/v1/policies", make_user(ws="ws1"))
    assert payload["workspace_id"] == "ws1"
    assert payload["policy"]["max_runs_per_day"] == 25
    assert payload["policy"]["network_modes"] == ["offline"]
    assert payload["quota"] == {"limits": {"runs": 10}, "used": {"runs": 3}}


def test_a_workspace_with_no_policy_says_none_rather_than_inventing_one() -> None:
    _status, payload = call("/api/v1/policies", make_user(ws="ws-unconfigured"))
    assert payload["policy"] is None
    assert payload["quota"] is None


# --- webhooks ----------------------------------------------------------------


def test_the_signing_secret_never_leaves_the_server() -> None:
    """It is the only thing that makes a delivery verifiable.

    Returning it here would hand every viewer the ability to forge one.
    """
    STATE.webhooks = WebhookDispatcher("super-secret-value", lambda *_: 200)
    STATE.webhooks.subscribe("https://example.test/hook", ["run.finished"])
    _status, payload = call("/api/v1/webhooks", make_user())
    assert "super-secret-value" not in json.dumps(payload)
    assert payload["webhooks"][0]["url"] == "https://example.test/hook"


def test_no_dispatcher_configured_is_stated_rather_than_shown_as_empty() -> None:
    """ "No webhooks" and "webhooks are not set up" are different facts."""
    STATE.webhooks = None
    _status, payload = call("/api/v1/webhooks", make_user())
    assert payload["webhooks"] == []
    assert payload["configured"] is False
    assert payload["note"]


# --- workers -----------------------------------------------------------------


def test_the_server_reports_its_own_node_and_says_so() -> None:
    """`tooltrace fleet` coordinates through a shared directory, not through
    this process, so a server asked for "the workers" honestly has one."""
    _status, payload = call("/api/v1/workers", make_user())
    assert len(payload["workers"]) == 1
    assert payload["workers"][0]["worker_id"] == "server"
    assert "fleet" in payload["note"]


def test_the_worker_row_reports_gpu_detection_rather_than_a_bare_false() -> None:
    """The defect this replaces: `WorkerInventory.gpu` defaulted to False and
    nothing set it, so every worker claimed to have no GPU."""
    _status, payload = call("/api/v1/workers", make_user())
    assert payload["workers"][0]["gpu_detection"] in {"found", "none_found", "not_detectable"}


# --- baselines ---------------------------------------------------------------


def test_no_registry_returns_an_empty_list_with_the_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _status, payload = call("/api/v1/baselines", make_user())
    assert payload["baselines"] == []
    assert "tooltrace-baselines.json" in payload["note"]


def test_the_registry_is_read_from_where_the_cli_writes_it(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path(".tooltrace-baselines.json").write_text(
        json.dumps({"nightly": "/runs/a.tooltrace"}), encoding="utf-8"
    )
    _status, payload = call("/api/v1/baselines", make_user())
    assert payload["baselines"] == [{"name": "nightly", "bundle": "/runs/a.tooltrace"}]


def test_a_corrupt_registry_does_not_take_the_endpoint_down(tmp_path, monkeypatch) -> None:
    """A half-written file is a fact about the disk, not a 500."""
    monkeypatch.chdir(tmp_path)
    Path(".tooltrace-baselines.json").write_text("{not json", encoding="utf-8")
    status, payload = call("/api/v1/baselines", make_user())
    assert status == 200
    assert payload["baselines"] == []
    assert "unreadable" in payload["note"]
