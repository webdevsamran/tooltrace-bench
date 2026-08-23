"""Generate the long-context scale-family task pack.

Writes deterministic YAML tasks whose workspace filler grows across scales
(1k / 4k / 16k chars) while the objective stays identical, so reliability,
steps and latency can be compared as context grows. CI-safe: all content is
generated locally, no network, tiny files.

Usage: python scripts/generate_longcontext_pack.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

PACK_DIR = Path("tooltrace/tasks/packs/long-context")
SCALES = {"1k": 1000, "4k": 4000, "16k": 16000}
FILLER_LINE = "lorem ipsum dolor sit amet "


def _filler(total_chars: int, index: int) -> str:
    """Deterministic filler of ~total_chars chars split across filler files."""
    per_file = max(total_chars // 4, 1)
    lines: list[str] = []
    size = 0
    i = 0
    while size < per_file:
        line = f"{FILLER_LINE * 8} (file {index} line {i})"
        lines.append(line)
        size += len(line) + 1
        i += 1
    return "\n".join(lines) + "\n"


def _task(scale: str, total_chars: int) -> dict[str, object]:
    workspace: dict[str, str] = {"target.txt": "status: reday\n"}
    n_files = max(total_chars // 1000, 1)
    for i in range(n_files):
        workspace[f"filler_{i}.txt"] = _filler(total_chars // n_files, i)
    return {
        "id": f"long-context/context-scale-{scale}",
        "name": f"Long-context scale {scale}",
        "version": "1.0.0",
        "category": "long-context",
        "difficulty": "medium",
        "tags": ["long-context", "scale", scale],
        "objective": (
            "Fix the typo in target.txt (replace 'reday' with 'ready'). "
            "Ignore the large irrelevant filler files."
        ),
        "description": (
            f"Long-context robustness probe at ~{total_chars} chars of "
            "distractor workspace content. Identical objective across the "
            "scale family; only context size varies."
        ),
        "starting_workspace": workspace,
        "allowed_tools": ["read_file", "patch_file", "search_text", "list_directory"],
        "assertions": [
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
        "expected_artifacts": [],
        "timeout_seconds": 60,
        "max_steps": 12,
        "network_policy": "disabled",
        "long_context": True,
        "metadata": {
            "context_chars": total_chars,
            "scripted_script": [
                {"tool": "search_text", "args": {"pattern": "reday"}},
                {
                    "tool": "patch_file",
                    "args": {"path": "target.txt", "search": "reday", "replace": "ready"},
                },
            ],
        },
    }


def main() -> int:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    for scale, chars in SCALES.items():
        doc = _task(scale, chars)
        target = PACK_DIR / f"context-scale-{scale}.yaml"
        target.write_text(yaml.safe_dump(doc, sort_keys=False, width=100), encoding="utf-8")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
