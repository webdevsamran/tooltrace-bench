"""Generate the built-in deterministic task packs (CI-safe, offline).

Run:  python scripts/generate_packs.py
Each task carries metadata.scripted_script — a reference solution executed by
the deterministic scripted agent, used by `tooltrace task test` and CI.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "tooltrace" / "tasks" / "packs"
NL = chr(10)


def lines(*rows: str) -> str:
    return NL.join(rows) + NL


def task(**kw) -> dict:
    kw.setdefault("version", "1.0.0")
    kw.setdefault("difficulty", "easy")
    kw.setdefault("tags", [])
    kw.setdefault("expected_artifacts", [])
    kw.setdefault("network_policy", "disabled")
    kw.setdefault("timeout_seconds", 60)
    kw.setdefault("max_steps", 10)
    kw.setdefault("metadata", {})
    return kw


PACKS: dict[str, list[dict]] = {
    "file-editing": [
        task(
            id="file-editing/fix-config-typo",
            name="Fix config key typo",
            category="file-editing",
            tags=["config", "typo"],
            objective="Fix the misspelled key 'timout' to 'timeout' in config.ini, preserving all other content.",
            description="config.ini contains a misspelled key. Correct it without altering any other line.",
            starting_workspace={
                "config.ini": lines("[server]", "host = localhost", "port = 8080", "timout = 30")
            },
            allowed_tools=[
                "read_file",
                "patch_file",
                "write_file",
                "list_directory",
                "search_text",
            ],
            assertions=[
                {
                    "type": "file_not_contains",
                    "params": {"path": "config.ini", "text": "timout"},
                    "weight": 1.0,
                    "description": "typo removed",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "config.ini", "any_of": ["timeout = 30"]},
                    "weight": 1.0,
                    "description": "correct key present",
                },
            ],
            expected_artifacts=["config.ini"],
            metadata={
                "scripted_script": [
                    {"tool": "read_file", "args": {"path": "config.ini"}},
                    {
                        "tool": "patch_file",
                        "args": {"path": "config.ini", "search": "timout", "replace": "timeout"},
                    },
                ]
            },
        )
    ],
    "bug-fixing": [
        task(
            id="bug-fixing/fix-off-by-one",
            name="Fix off-by-one in average()",
            category="bug-fixing",
            tags=["python", "loop"],
            objective="Fix the off-by-one bug in stats.py so the test suite passes.",
            description="average() skips the last element. Fix it and verify with the bundled test.",
            starting_workspace={
                "stats.py": lines(
                    "def average(nums):",
                    "    total = 0",
                    "    for i in range(len(nums) - 1):",
                    "        total += nums[i]",
                    "    return total / len(nums)",
                ),
                "test_stats.py": lines(
                    "from stats import average",
                    "",
                    "def test_average():",
                    "    assert average([1, 2, 3]) == 2",
                ),
            },
            allowed_tools=[
                "read_file",
                "patch_file",
                "write_file",
                "list_directory",
                "test_runner",
                "shell",
            ],
            assertions=[
                {
                    "type": "tests_pass",
                    "params": {"path": "."},
                    "weight": 1.0,
                    "description": "test suite passes",
                }
            ],
            expected_artifacts=["stats.py"],
            metadata={
                "scripted_script": [
                    {
                        "tool": "patch_file",
                        "args": {
                            "path": "stats.py",
                            "search": "range(len(nums) - 1)",
                            "replace": "range(len(nums))",
                        },
                    },
                    {"tool": "test_runner", "args": {}},
                ]
            },
        )
    ],
    "test-repair": [
        task(
            id="test-repair/fix-test-expectation",
            name="Fix incorrect test expectation",
            category="test-repair",
            tags=["pytest"],
            objective="The implementation of add() is correct; fix the wrong expectation in test_calc.py.",
            description="test_calc.py asserts add(2, 2) == 5. The correct expectation is 4. Repair the test, not the implementation.",
            starting_workspace={
                "calc.py": lines("def add(a, b):", "    return a + b"),
                "test_calc.py": lines(
                    "from calc import add", "", "def test_add():", "    assert add(2, 2) == 5"
                ),
            },
            allowed_tools=["read_file", "patch_file", "write_file", "test_runner"],
            assertions=[
                {
                    "type": "tests_pass",
                    "params": {"path": "."},
                    "weight": 1.0,
                    "description": "tests pass",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "calc.py", "text": "return a + b"},
                    "weight": 1.0,
                    "description": "implementation untouched",
                },
            ],
            metadata={
                "scripted_script": [
                    {
                        "tool": "patch_file",
                        "args": {"path": "test_calc.py", "search": "== 5", "replace": "== 4"},
                    },
                    {"tool": "test_runner", "args": {}},
                ]
            },
        )
    ],
    "refactoring": [
        task(
            id="refactoring/rename-function",
            name="Rename compute_total to calculate_sum",
            category="refactoring",
            tags=["rename"],
            objective="Rename compute_total to calculate_sum everywhere in utils.py, keeping behavior identical.",
            description="Pure rename refactor; the report() call site must be updated too.",
            starting_workspace={
                "utils.py": lines(
                    "def compute_total(items):",
                    "    return sum(items)",
                    "",
                    "",
                    "def report(items):",
                    "    return compute_total(items)",
                )
            },
            allowed_tools=["read_file", "patch_file", "write_file", "search_text"],
            assertions=[
                {
                    "type": "ast_check",
                    "params": {
                        "path": "utils.py",
                        "defines": ["calculate_sum", "report"],
                        "not_defines": ["compute_total"],
                    },
                    "weight": 1.0,
                    "description": "renamed definitions",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "utils.py", "text": "return calculate_sum(items)"},
                    "weight": 1.0,
                    "description": "call site updated",
                },
            ],
            metadata={
                "scripted_script": [
                    {
                        "tool": "write_file",
                        "args": {
                            "path": "utils.py",
                            "content": lines(
                                "def calculate_sum(items):",
                                "    return sum(items)",
                                "",
                                "",
                                "def report(items):",
                                "    return calculate_sum(items)",
                            ),
                        },
                    },
                ]
            },
        )
    ],
    "docs-correction": [
        task(
            id="docs-correction/fix-install-command",
            name="Fix install command in README",
            category="docs-correction",
            tags=["docs"],
            objective="Correct the misspelled install command in README.md.",
            description="'pip instal' must become 'pip install'.",
            starting_workspace={
                "README.md": lines("# Demo", "", "Install:", "", "    pip instal tooltrace-bench")
            },
            allowed_tools=["read_file", "patch_file", "write_file"],
            assertions=[
                {
                    "type": "file_not_contains",
                    "params": {"path": "README.md", "text": "pip instal "},
                    "weight": 1.0,
                    "description": "typo removed",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "README.md", "text": "pip install tooltrace-bench"},
                    "weight": 1.0,
                    "description": "correct command",
                },
            ],
            metadata={
                "scripted_script": [
                    {
                        "tool": "patch_file",
                        "args": {
                            "path": "README.md",
                            "search": "pip instal",
                            "replace": "pip install",
                        },
                    },
                ]
            },
        )
    ],
    "json-csv-transform": [
        task(
            id="json-csv-transform/users-to-csv",
            name="Convert users.json to users.csv",
            category="json-csv-transform",
            tags=["json", "csv"],
            objective="Convert users.json into users.csv with a header row name,age.",
            description="Read users.json and write users.csv with columns name,age in the same order.",
            starting_workspace={
                "users.json": '[{"name": "Ada", "age": 36}, {"name": "Lin", "age": 28}]'
            },
            allowed_tools=["read_file", "write_file", "list_directory"],
            assertions=[
                {
                    "type": "file_exists",
                    "params": {"path": "users.csv"},
                    "weight": 1.0,
                    "description": "csv created",
                },
                {
                    "type": "csv_equals",
                    "params": {
                        "path": "users.csv",
                        "expected_csv": lines("name,age", "Ada,36", "Lin,28"),
                    },
                    "weight": 1.0,
                    "description": "csv content exact",
                },
            ],
            expected_artifacts=["users.csv"],
            metadata={
                "scripted_script": [
                    {
                        "tool": "write_file",
                        "args": {
                            "path": "users.csv",
                            "content": lines("name,age", "Ada,36", "Lin,28"),
                        },
                    },
                ]
            },
        )
    ],
    "git-workflow": [
        task(
            id="git-workflow/commit-fix",
            name="Commit a fix with git",
            category="git-workflow",
            tags=["git", "shell"],
            objective="Fix the typo in app.py and create a git commit containing the fix.",
            description="Initialize a git repository if needed, fix the typo, stage and commit with any message.",
            starting_workspace={"app.py": lines("def greet(name):", "    return 'Helo, ' + name")},
            allowed_tools=["read_file", "patch_file", "write_file", "shell", "git"],
            assertions=[
                {
                    "type": "file_not_contains",
                    "params": {"path": "app.py", "text": "Helo"},
                    "weight": 1.0,
                    "description": "typo fixed",
                },
                {
                    "type": "command_exit",
                    "params": {"command": "git rev-parse HEAD", "expect_code": 0},
                    "weight": 1.0,
                    "description": "a commit exists",
                },
                {
                    "type": "command_exit",
                    "params": {"command": "git diff --quiet HEAD", "expect_code": 0},
                    "weight": 1.0,
                    "description": "working tree clean",
                },
            ],
            timeout_seconds=90,
            metadata={
                "scripted_script": [
                    {
                        "tool": "patch_file",
                        "args": {"path": "app.py", "search": "Helo", "replace": "Hello"},
                    },
                    {
                        "tool": "shell",
                        "args": {
                            "command": "git init -q && git add -A && git -c user.email=agent@example.test -c user.name=Agent commit -qm fix-greeting"
                        },
                    },
                ]
            },
        )
    ],
    "shell-workflow": [
        task(
            id="shell-workflow/create-structure",
            name="Create project structure",
            category="shell-workflow",
            tags=["shell"],
            objective="Create src/main.py containing a line with hello.",
            description="Use any tools to create the directory src and the file src/main.py that prints hello.",
            starting_workspace={},
            allowed_tools=["shell", "write_file", "list_directory"],
            assertions=[
                {
                    "type": "file_exists",
                    "params": {"path": "src/main.py"},
                    "weight": 1.0,
                    "description": "file created",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "src/main.py", "text": "hello"},
                    "weight": 1.0,
                    "description": "content correct",
                },
            ],
            expected_artifacts=["src/main.py"],
            metadata={
                "scripted_script": [
                    {"tool": "shell", "args": {"command": "mkdir src"}},
                    {
                        "tool": "write_file",
                        "args": {"path": "src/main.py", "content": lines("print('hello')")},
                    },
                ]
            },
        )
    ],
    "mock-api": [
        task(
            id="mock-api/activate-user",
            name="Activate user in local API state",
            category="mock-api",
            tags=["api-state"],
            objective="Set users[0].active to true in the local mock API state file.",
            description="state.json represents a local mock API's persisted state. Flip the first user's active flag to true.",
            starting_workspace={
                "state.json": '{"users": [{"id": 1, "name": "Ada", "active": false}]}'
            },
            allowed_tools=["read_file", "patch_file", "write_file"],
            assertions=[
                {
                    "type": "api_state",
                    "params": {"file": "state.json", "json_path": "users.0.active", "equals": True},
                    "weight": 1.0,
                    "description": "user active",
                },
                {
                    "type": "api_state",
                    "params": {"file": "state.json", "json_path": "users.0.name", "equals": "Ada"},
                    "weight": 1.0,
                    "description": "other fields preserved",
                },
            ],
            metadata={
                "scripted_script": [
                    {
                        "tool": "patch_file",
                        "args": {
                            "path": "state.json",
                            "search": '"active": false',
                            "replace": '"active": true',
                        },
                    },
                ]
            },
        )
    ],
    "data-analysis": [
        task(
            id="data-analysis/summarize-numbers",
            name="Summarize numbers.csv",
            category="data-analysis",
            tags=["csv", "math"],
            objective="Write summary.json with count, sum and mean of the value column in numbers.csv.",
            description="numbers.csv has a header 'value' and five rows. Compute count=5, sum=15, mean=3.0 and write summary.json.",
            starting_workspace={"numbers.csv": lines("value", "1", "2", "3", "4", "5")},
            allowed_tools=["read_file", "calculator", "write_file"],
            assertions=[
                {
                    "type": "json_equals",
                    "params": {
                        "path": "summary.json",
                        "expected": {"count": 5, "sum": 15, "mean": 3.0},
                    },
                    "weight": 1.0,
                    "description": "summary exact",
                },
            ],
            expected_artifacts=["summary.json"],
            metadata={
                "scripted_script": [
                    {"tool": "read_file", "args": {"path": "numbers.csv"}},
                    {"tool": "calculator", "args": {"expression": "1+2+3+4+5"}},
                    {"tool": "calculator", "args": {"expression": "15/5"}},
                    {
                        "tool": "write_file",
                        "args": {
                            "path": "summary.json",
                            "content": '{"count": 5, "sum": 15, "mean": 3.0}',
                        },
                    },
                ]
            },
        )
    ],
    "multi-step-planning": [
        task(
            id="multi-step-planning/clean-orders",
            name="Clean orders and write report",
            category="multi-step-planning",
            tags=["pipeline"],
            difficulty="medium",
            objective="Filter orders.csv to status=ok rows into processed/orders_clean.csv and write report.txt containing the kept count.",
            description="Multi-step: read, transform, write two artifacts.",
            starting_workspace={"orders.csv": lines("id,status", "1,ok", "2,failed", "3,ok")},
            allowed_tools=["read_file", "write_file", "list_directory"],
            assertions=[
                {
                    "type": "file_exists",
                    "params": {"path": "processed/orders_clean.csv"},
                    "weight": 1.0,
                    "description": "clean csv exists",
                },
                {
                    "type": "csv_equals",
                    "params": {
                        "path": "processed/orders_clean.csv",
                        "expected_csv": lines("id,status", "1,ok", "3,ok"),
                    },
                    "weight": 1.0,
                    "description": "rows filtered",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "report.txt", "text": "2"},
                    "weight": 1.0,
                    "description": "report has count",
                },
            ],
            expected_artifacts=["processed/orders_clean.csv", "report.txt"],
            metadata={
                "scripted_script": [
                    {"tool": "read_file", "args": {"path": "orders.csv"}},
                    {
                        "tool": "write_file",
                        "args": {
                            "path": "processed/orders_clean.csv",
                            "content": lines("id,status", "1,ok", "3,ok"),
                        },
                    },
                    {
                        "tool": "write_file",
                        "args": {"path": "report.txt", "content": lines("kept 2 orders")},
                    },
                ]
            },
        ),
        task(
            id="multi-step-planning/long-context-notes",
            name="Edit target file inside noisy long context",
            category="multi-step-planning",
            tags=["long-context", "noise"],
            difficulty="medium",
            objective="Fix the typo in target.txt despite many large irrelevant files in the workspace.",
            description="Long-context robustness probe: the workspace contains several large filler files; only target.txt matters.",
            starting_workspace={
                "target.txt": lines("status: reday"),
                **{f"filler_{i}.txt": ("lorem ipsum dolor sit amet " * 400) + NL for i in range(6)},
            },
            allowed_tools=[
                "read_file",
                "patch_file",
                "write_file",
                "search_text",
                "list_directory",
            ],
            assertions=[
                {
                    "type": "file_not_contains",
                    "params": {"path": "target.txt", "text": "reday"},
                    "weight": 1.0,
                    "description": "typo fixed",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "target.txt", "text": "ready"},
                    "weight": 1.0,
                    "description": "correct word",
                },
            ],
            max_steps=12,
            metadata={
                "scripted_script": [
                    {"tool": "search_text", "args": {"pattern": "reday"}},
                    {
                        "tool": "patch_file",
                        "args": {"path": "target.txt", "search": "reday", "replace": "ready"},
                    },
                ]
            },
        ),
    ],
    "failure-recovery": [
        task(
            id="failure-recovery/retry-after-tool-failure",
            name="Recover from transient tool failure",
            category="failure-recovery",
            tags=["recovery", "perturbation"],
            difficulty="medium",
            objective="Fix the typo in notes.txt even though the first read_file call fails transiently.",
            description="The harness injects one transient failure into the first read_file call. A reliable agent retries and completes.",
            starting_workspace={"notes.txt": lines("deploy is reday")},
            allowed_tools=["read_file", "patch_file", "write_file"],
            assertions=[
                {
                    "type": "file_not_contains",
                    "params": {"path": "notes.txt", "text": "reday"},
                    "weight": 1.0,
                    "description": "typo fixed",
                },
                {
                    "type": "file_contains",
                    "params": {"path": "notes.txt", "text": "ready"},
                    "weight": 1.0,
                    "description": "correct word",
                },
            ],
            perturbations=[{"kind": "tool_failure", "params": {"tool": "read_file"}}],
            metadata={
                "scripted_script": [
                    {"tool": "read_file", "args": {"path": "notes.txt"}},
                    {"tool": "read_file", "args": {"path": "notes.txt"}},
                    {
                        "tool": "patch_file",
                        "args": {"path": "notes.txt", "search": "reday", "replace": "ready"},
                    },
                ]
            },
        ),
    ],
}


def main() -> None:
    count = 0
    for pack, tasks in PACKS.items():
        pack_dir = ROOT / pack
        pack_dir.mkdir(parents=True, exist_ok=True)
        for t in tasks:
            slug = str(t["id"]).split("/")[-1]
            target = pack_dir / f"{slug}.yaml"
            target.write_text(yaml.safe_dump(t, sort_keys=False), encoding="utf-8")
            count += 1
    print(f"wrote {count} tasks across {len(PACKS)} packs under {ROOT}")


if __name__ == "__main__":
    main()
