# Plugins & Extensions

ToolTrace Bench is extensible through Python entry-point groups. Third-party
packages register implementations; the core never auto-installs or
auto-executes remote code — installing a plugin package is always an explicit
user action.

## Entry-point groups

| Group | Contract | Built-ins |
|---|---|---|
| `tooltrace.agents` | `AgentAdapter`: initialize / run / event stream / usage / artifacts | subprocess, openai_compat, scripted |
| `tooltrace.tools` | typed tool with sanitized event emission | read/write/patch/list/search files, shell, git, calculator, test_runner, http |
| `tooltrace.task_packs` | pack directory with YAML task definitions | builtin |
| `tooltrace.scorers` | deterministic scorer functions | 13 built-in scorers |
| `tooltrace.reporters` | report exporters (JSON/CSV/MD/JUnit/HTML) | 5 exporters |
| `tooltrace.sandboxes` | sandbox providers | local temp workspace, Docker (+Podman-compatible interface) |

Example registration in your package metadata:

```toml
[project.entry-points."tooltrace.agents"]
my_agent = "my_pkg.agent:MyAgent"
```

## Versioning and compatibility

- Plugin APIs carry semantic versions and compatibility ranges; adapters
  declare capabilities (streaming, tool calls, images, audio, JSON mode,
  reasoning metadata, usage accounting) negotiated at startup.
- Scorer plugin API v2 requires deterministic/non-deterministic declaration;
  non-deterministic (model-judge) scorers are reported separately and never
  silently averaged into pass/fail.
- Every artifact records the schema/protocol/producer versions that produced
  it — see [schemas-and-protocols.md](schemas-and-protocols.md).

## Authoring checklist

1. Scaffold: `tooltrace task scaffold` (tasks) or copy a minimal adapter.
2. Validate: `tooltrace validate` → `tooltrace lint` → `tooltrace dry-run`
   (no model needed).
3. Conformance: run the conformance tests for your group — agent adapters are
   exercised against scripted fixtures; MCP server implementations against
   the bundled conformance fixtures with a fake server.
4. Failure isolation: a crashing plugin must not corrupt the host run; wrap
   boundaries and raise typed exceptions from `tooltrace.core.exceptions`.
5. Diagnostics: `tooltrace doctor` lists discovered plugins and their
   declared capabilities so users can debug installations.

## Distribution conventions

- Ship packs/plugins as ordinary PyPI packages; document the exact versions
  of tooltrace-bench you tested against.
- Catalog/marketplace metadata is generated from trusted repository/plugin
  manifests for display only — installation remains manual.
