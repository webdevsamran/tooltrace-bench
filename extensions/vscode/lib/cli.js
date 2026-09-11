/**
 * Everything the extension does that does not need VS Code to be running.
 *
 * `extension.js` is the half that calls `vscode.*`, and it is deliberately thin:
 * an extension whose logic lives behind the editor API can only be tested by
 * downloading an editor, so in practice it is not tested at all. Argument
 * building, output parsing, grouping and HTML rendering all live here instead,
 * and `test/cli.test.js` runs them under plain `node --test` with no
 * dependencies to install.
 *
 * The other half of the honesty problem is rot. An extension that shells out to
 * a CLI is a second, unchecked copy of that CLI's interface, and this project
 * has already shipped documentation naming a flag the CLI never had.
 * `INVOCATIONS` is therefore a table rather than strings scattered through the
 * code, and `tests/test_vscode_extension_matches_the_cli.py` feeds every entry
 * in it to the real argument parser.
 *
 * This extension does not bundle tooltrace and never installs it. It runs
 * whatever `tooltrace` is on PATH, or `tooltrace.executablePath` when set.
 */

'use strict';

/**
 * Every command line this extension can produce.
 *
 * `args` is a template: a string is passed through, and a `{name}` placeholder
 * is substituted from the params object. Flags are listed even when their value
 * is a placeholder, because the flag is the part that rots.
 */
const INVOCATIONS = {
  listTasks: { args: ['tasks', '--json'] },
  listAgents: { args: ['agents', '--json'] },
  doctor: { args: ['doctor', '--json'] },
  runTask: { args: ['run', '--task', '{task}', '--agent', '{agent}', '--json'] },
  openTrace: { args: ['trace', '{bundle}', '--json'] },
  verifyBundle: { args: ['verify', '{bundle}', '--json'] },
  lintPack: { args: ['lint', '--path', '{path}', '--json'] },
};

class MissingParameter extends Error {}

/**
 * Fill an invocation template. Throws on a placeholder with no value, rather
 * than sending the literal `{task}` to the CLI and reporting its complaint.
 */
function buildArgs(name, params) {
  const spec = INVOCATIONS[name];
  if (!spec) throw new MissingParameter(`no such invocation: ${name}`);
  return spec.args.map((token) => {
    const match = /^\{(\w+)\}$/.exec(token);
    if (!match) return token;
    const value = (params || {})[match[1]];
    if (value === undefined || value === null || value === '') {
      throw new MissingParameter(`${name} needs a value for ${match[1]}`);
    }
    return String(value);
  });
}

/**
 * Parse a `--json` response.
 *
 * Strict on purpose. Several commands used to print "wrote 3 draft task(s)"
 * before their JSON, and a parser that skipped to the first `{` would have
 * hidden that instead of surfacing it. The raw text goes in the error so the
 * user can see what actually came back.
 */
function parseJson(stdout) {
  const text = String(stdout == null ? '' : stdout).trim();
  if (!text) throw new Error('the command produced no output');
  try {
    return JSON.parse(text);
  } catch (err) {
    const head = text.length > 200 ? `${text.slice(0, 200)}...` : text;
    throw new Error(`expected JSON from --json, got: ${head}`);
  }
}

/** Group `tasks --json` rows into pack -> tasks, for the tree view. */
function tasksToTree(rows) {
  const packs = new Map();
  for (const row of rows || []) {
    const id = String(row.id || '');
    const pack = id.includes('/') ? id.split('/')[0] : '(unknown)';
    if (!packs.has(pack)) packs.set(pack, []);
    packs.get(pack).push({
      id,
      name: id.includes('/') ? id.slice(id.indexOf('/') + 1) : id,
      difficulty: row.difficulty || '',
      // Surfaced rather than hidden: a task this machine cannot run is not a
      // broken task, and an editor that greyed it out with no reason would
      // look like a bug in the extension.
      runnable: row.runnable_here !== false,
      attachments: Number(row.attachments || 0),
    });
  }
  return [...packs.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([pack, tasks]) => ({ pack, tasks: tasks.sort((a, b) => a.id.localeCompare(b.id)) }));
}

/**
 * A one-line verdict for a `run --json` payload.
 *
 * A skipped task is reported as skipped. It is not a failure -- the agent was
 * never shown the question, either because a toolchain is missing or because
 * the adapter cannot be sent the task's attachments -- and an editor that said
 * "failed" would be making a claim the harness deliberately refuses to make.
 */
function describeRun(payload) {
  const data = payload || {};
  if (data.skipped) {
    return { kind: 'skipped', message: `skipped ${data.task_id || ''}: ${data.reason || ''}`.trim() };
  }
  const score = data.score && typeof data.score.total === 'number' ? data.score.total : null;
  const suffix = score === null ? '' : ` (score ${score.toFixed(2)})`;
  return data.success
    ? { kind: 'pass', message: `passed ${data.task_id || ''}${suffix}`.trim() }
    : {
        kind: 'fail',
        message: `failed ${data.task_id || ''}${suffix}${
          data.failure_reason ? ` -- ${data.failure_reason}` : ''
        }`.trim(),
      };
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Render a trace as a webview document.
 *
 * Every value is escaped and the CSP forbids scripts. A trace holds whatever
 * the agent wrote and whatever the tools returned, which is untrusted text by
 * construction: a prompt-injection payload from a task fixture would otherwise
 * be markup executing inside the user's editor. This project ships tasks whose
 * entire purpose is to contain such a payload.
 */
function traceToHtml(events, title) {
  const rows = (events || [])
    .map((event) => {
      const detail =
        typeof event.detail === 'string' ? event.detail : JSON.stringify(event.detail ?? '');
      return [
        '<tr>',
        `<td class="seq">${escapeHtml(event.seq ?? '')}</td>`,
        `<td class="kind">${escapeHtml(event.type || event.kind || '')}</td>`,
        `<td class="tool">${escapeHtml(event.tool || '')}</td>`,
        `<td class="detail"><pre>${escapeHtml(detail)}</pre></td>`,
        '</tr>',
      ].join('');
    })
    .join('\n');

  return [
    '<!DOCTYPE html>',
    '<html lang="en"><head><meta charset="utf-8">',
    '<meta http-equiv="Content-Security-Policy" ',
    'content="default-src \'none\'; style-src \'unsafe-inline\';">',
    `<title>${escapeHtml(title || 'trace')}</title>`,
    '<style>',
    'body{font:13px var(--vscode-editor-font-family,monospace);padding:8px}',
    'table{border-collapse:collapse;width:100%}',
    'td{border-bottom:1px solid var(--vscode-panel-border,#3336);',
    'padding:4px 6px;vertical-align:top}',
    '.seq{text-align:right;opacity:.6;width:3em}',
    '.kind{white-space:nowrap}.tool{white-space:nowrap;opacity:.8}',
    'pre{margin:0;white-space:pre-wrap;word-break:break-word}',
    '</style></head><body>',
    `<h1>${escapeHtml(title || 'trace')}</h1>`,
    (events || []).length
      ? `<table><tbody>${rows}</tbody></table>`
      : '<p>This bundle records no trace events.</p>',
    '</body></html>',
  ].join('\n');
}

/**
 * What to tell a user whose `tooltrace` could not be started.
 *
 * Named separately because "command not found" from a spawned process is the
 * single most likely failure of this extension, and the message has to say what
 * to do rather than repeat the errno.
 */
function missingExecutableMessage(executable) {
  return (
    `Could not run \`${executable}\`. ToolTrace Bench is a Python package and this ` +
    'extension does not bundle it: install it (`pip install tooltrace-bench`) or set ' +
    '`tooltrace.executablePath` to the interpreter entry point you use.'
  );
}

module.exports = {
  INVOCATIONS,
  MissingParameter,
  buildArgs,
  describeRun,
  escapeHtml,
  missingExecutableMessage,
  parseJson,
  tasksToTree,
  traceToHtml,
};
