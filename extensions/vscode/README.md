# ToolTrace Bench for VS Code

Run a task and read its trace without leaving the editor.

This extension is a **front end to the `tooltrace` command line**, not a second
implementation of it. It does not bundle, vendor or install ToolTrace Bench: it
runs whatever `tooltrace` is on your `PATH`, or the one you name in
`tooltrace.executablePath`. A bundled copy would drift from your installed one,
and the two would disagree about results while looking identical.

## What it does

| Command | What it runs |
|---|---|
| **ToolTrace: Run a task** | `tooltrace run --task ID --agent A --json` |
| **ToolTrace: Open a bundle trace** | `tooltrace trace BUNDLE --json`, rendered in a webview |
| **ToolTrace: Verify a bundle** | `tooltrace verify BUNDLE --json` |
| **ToolTrace: Lint a task pack** | `tooltrace lint --path DIR --json` (exit 3 on findings is a finding, not a broken run) |
| **ToolTrace: Doctor** | `tooltrace doctor --json` |
| **ToolTrace: Refresh tasks** | `tooltrace tasks --json`, into the Explorer tree |

The Explorer gets a **ToolTrace Tasks** view: packs, then tasks, with difficulty
and -- where it applies -- `not runnable here`. A task this machine cannot run
is shown and labelled rather than hidden, because a missing toolchain is a fact
about the machine and an absent row would look like a bug in the extension.

A **skipped** run is reported as skipped, never as a failure. The agent was not
shown the question, so there is nothing to score.

## Install

There is no build step and no `node_modules`. Copy or symlink this directory
into your extensions folder:

```bash
ln -s "$PWD/extensions/vscode" ~/.vscode/extensions/tooltrace-bench
```

Then install the CLI it drives, if you have not:

```bash
pip install tooltrace-bench
```

## Why there is no TypeScript here

VS Code loads CommonJS directly, so the shipped files are the source files:
nothing to compile, no bundler, no lockfile to go stale, and no build artifact
in the repository that nothing regenerates. It is the same reasoning that keeps
the dashboard's charts hand-rolled SVG.

## How it is tested

Two halves, for two different failure modes.

`lib/cli.js` holds everything that does not need an editor -- argument building,
output parsing, grouping, HTML rendering -- and `test/cli.test.js` exercises it
under the test runner built into Node:

```bash
node --test test/cli.test.js
```

No dependencies, nothing to install. `extension.js` is the thin remainder: it
collects a choice, calls a pure function, spawns the process. An extension whose
logic sits behind `vscode.window.*` can only be tested by downloading an editor,
which in practice means it is not tested.

The second failure mode is rot. An extension that shells out to a CLI holds an
unchecked copy of that CLI's interface, and this project has shipped that exact
bug in its own documentation before. So the command lines live in one table --
`INVOCATIONS` in `lib/cli.js` -- and
`tests/test_vscode_extension_matches_the_cli.py` feeds every entry to the real
argument parser. A flag renamed in Python fails the Python suite, not your
editor.

## Security

The trace webview runs with `enableScripts: false` and a
`default-src 'none'` CSP, and every value in it is escaped. This is not
theoretical: this project ships tasks whose entire purpose is to plant a
prompt-injection payload in a file an agent reads, and that payload ends up in
the trace you are about to look at.
