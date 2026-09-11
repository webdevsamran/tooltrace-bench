/**
 * The extension's logic, under plain `node --test`. No install, no editor.
 *
 * Run it with `node --test extensions/vscode/test/` from the repository root,
 * or `npm test` from this directory. There is no `node_modules`: the test
 * runner is the one built into Node, and nothing here requires `vscode`.
 *
 * `tests/test_vscode_extension_matches_the_cli.py` is the other half -- it
 * feeds every entry in `INVOCATIONS` to the real argument parser, so a flag
 * renamed in Python fails the Python suite rather than a user's editor.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');

const {
  INVOCATIONS,
  MissingParameter,
  buildArgs,
  describeRun,
  escapeHtml,
  missingExecutableMessage,
  parseJson,
  tasksToTree,
  traceToHtml,
} = require('../lib/cli');

test('every invocation asks for --json', () => {
  for (const [name, spec] of Object.entries(INVOCATIONS)) {
    assert.ok(spec.args.includes('--json'), `${name} does not request --json`);
  }
});

test('a placeholder with no value is refused, not sent literally', () => {
  assert.throws(() => buildArgs('runTask', { task: 'a/b' }), MissingParameter);
  assert.throws(() => buildArgs('runTask', { task: 'a/b', agent: '' }), MissingParameter);
});

test('placeholders are substituted and nothing else is', () => {
  assert.deepStrictEqual(buildArgs('runTask', { task: 'demo/x', agent: 'scripted' }), [
    'run',
    '--task',
    'demo/x',
    '--agent',
    'scripted',
    '--json',
  ]);
});

test('a value that looks like a flag is still one argument', () => {
  // execFile does not use a shell, so this is passed as a single argv entry
  // rather than being re-split. Asserted so a future switch to `exec` breaks
  // here rather than in somebody's shell.
  const args = buildArgs('openTrace', { bundle: '--not-a-flag; rm -rf /' });
  assert.strictEqual(args[1], '--not-a-flag; rm -rf /');
});

test('parseJson is strict about output that is not JSON', () => {
  assert.deepStrictEqual(parseJson('{"a": 1}'), { a: 1 });
  assert.throws(() => parseJson('wrote 3 draft task(s)\n{"a":1}'), /expected JSON/);
  assert.throws(() => parseJson('   '), /no output/);
});

test('the parse error carries the output that caused it', () => {
  assert.throws(() => parseJson('Traceback (most recent call last):'), /Traceback/);
});

test('tasks are grouped by pack and sorted', () => {
  const tree = tasksToTree([
    { id: 'zeta/b', difficulty: 'hard' },
    { id: 'alpha/b' },
    { id: 'alpha/a', difficulty: 'easy' },
  ]);
  assert.deepStrictEqual(
    tree.map((group) => group.pack),
    ['alpha', 'zeta'],
  );
  assert.deepStrictEqual(
    tree[0].tasks.map((task) => task.id),
    ['alpha/a', 'alpha/b'],
  );
});

test('a task that cannot run here says so instead of vanishing', () => {
  const [group] = tasksToTree([{ id: 'a/b', runnable_here: false, attachments: 1 }]);
  assert.strictEqual(group.tasks[0].runnable, false);
  assert.strictEqual(group.tasks[0].attachments, 1);
});

test('runnable defaults to true when the CLI does not say', () => {
  const [group] = tasksToTree([{ id: 'a/b' }]);
  assert.strictEqual(group.tasks[0].runnable, true);
});

test('a skipped run is reported as skipped, not as a failure', () => {
  const verdict = describeRun({ task_id: 'a/b', skipped: true, reason: 'no cargo on PATH' });
  assert.strictEqual(verdict.kind, 'skipped');
  assert.match(verdict.message, /no cargo/);
});

test('a pass and a fail are distinguishable and carry the score', () => {
  assert.strictEqual(describeRun({ success: true, score: { total: 1 } }).kind, 'pass');
  const failed = describeRun({
    task_id: 'a/b',
    success: false,
    score: { total: 0.25 },
    failure_reason: 'bad_arguments',
  });
  assert.strictEqual(failed.kind, 'fail');
  assert.match(failed.message, /0\.25/);
  assert.match(failed.message, /bad_arguments/);
});

test('a run with no score does not print NaN', () => {
  assert.strictEqual(describeRun({ task_id: 'a/b', success: true }).message, 'passed a/b');
});

test('trace HTML escapes everything that came out of the run', () => {
  // Not hypothetical: this project ships tasks whose entire purpose is to put a
  // prompt-injection payload into a file an agent reads, and that payload ends
  // up in the trace. Unescaped, it would be markup running in the editor.
  const html = traceToHtml([
    { seq: 1, type: 'tool_call', tool: 'read_file', detail: '<img src=x onerror=alert(1)>' },
  ]);
  assert.ok(!html.includes('<img src=x'), 'the payload survived into the document');
  assert.ok(html.includes('&lt;img src=x'));
});

test('the webview forbids scripts in its own document', () => {
  const html = traceToHtml([]);
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /default-src 'none'/);
});

test('an empty trace says so rather than rendering an empty table', () => {
  assert.match(traceToHtml([], 'x'), /records no trace events/);
});

test('a non-string detail is serialized rather than printed as [object Object]', () => {
  const html = traceToHtml([{ seq: 1, type: 'tool_result', detail: { path: 'a.txt' } }]);
  assert.ok(html.includes('a.txt'));
  assert.ok(!html.includes('[object Object]'));
});

test('escapeHtml handles null and undefined without printing them', () => {
  assert.strictEqual(escapeHtml(null), '');
  assert.strictEqual(escapeHtml(undefined), '');
});

test('the missing-executable message says what to do', () => {
  const message = missingExecutableMessage('tooltrace');
  assert.match(message, /pip install/);
  assert.match(message, /executablePath/);
  assert.ok(
    !/bundl(e|ed|es)\b(?!.*does not)/.test(message.replace('does not bundle', '')),
    'the extension must not imply it ships tooltrace',
  );
});
