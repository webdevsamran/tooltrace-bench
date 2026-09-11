/**
 * The half that needs VS Code to be running, kept as thin as it can be.
 *
 * Nothing here decides anything: it collects a choice from the user, calls a
 * pure function in `lib/cli.js` to build the command line, spawns it, and hands
 * the output back to another pure function. That split is why `lib/` has tests
 * and this file has none -- testing it would mean downloading an editor, and an
 * extension whose logic sits behind `vscode.window.*` is one nobody checks.
 *
 * No build step, no bundler, no `node_modules`. VS Code loads CommonJS
 * directly, and the only module required at runtime that is not in this
 * directory is `vscode` itself, which the host provides.
 */

'use strict';

const { execFile } = require('node:child_process');
const path = require('node:path');
const vscode = require('vscode');

const {
  buildArgs,
  describeRun,
  missingExecutableMessage,
  parseJson,
  tasksToTree,
  traceToHtml,
} = require('./lib/cli');

/** Where the CLI is. Configured or on PATH -- never bundled. */
function executable() {
  const configured = vscode.workspace.getConfiguration('tooltrace').get('executablePath');
  return configured && String(configured).trim() ? String(configured).trim() : 'tooltrace';
}

function workspaceRoot() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length ? folders[0].uri.fsPath : undefined;
}

/** Spawn the CLI and parse its `--json`. Rejects with a message a user can act on. */
function run(name, params) {
  const command = executable();
  const args = buildArgs(name, params);
  return new Promise((resolve, reject) => {
    execFile(
      command,
      args,
      { cwd: workspaceRoot(), maxBuffer: 32 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error && error.code === 'ENOENT') {
          reject(new Error(missingExecutableMessage(command)));
          return;
        }
        try {
          // Not gated on the exit code: several commands exit non-zero *and*
          // report why in their JSON -- `lint` exits 3 on findings, `verify`
          // exits 5 on a problem -- and those are the runs worth reading.
          resolve(parseJson(stdout));
        } catch (parseError) {
          reject(new Error(`${parseError.message}${stderr ? `\n${String(stderr).trim()}` : ''}`));
        }
      },
    );
  });
}

class TaskTreeProvider {
  constructor() {
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._emitter.event;
    this._groups = [];
  }

  async refresh() {
    try {
      this._groups = tasksToTree(await run('listTasks'));
    } catch (error) {
      this._groups = [];
      vscode.window.showErrorMessage(error.message);
    }
    this._emitter.fire(undefined);
  }

  getTreeItem(element) {
    if (element.pack) {
      const item = new vscode.TreeItem(
        element.pack,
        vscode.TreeItemCollapsibleState.Collapsed,
      );
      item.description = `${element.tasks.length} task(s)`;
      return item;
    }
    const item = new vscode.TreeItem(element.name, vscode.TreeItemCollapsibleState.None);
    const notes = [element.difficulty];
    if (element.attachments) notes.push(`${element.attachments} attachment(s)`);
    if (!element.runnable) notes.push('not runnable here');
    item.description = notes.filter(Boolean).join(' | ');
    item.tooltip = element.id;
    item.command = {
      command: 'tooltrace.runTask',
      title: 'Run this task',
      arguments: [element.id],
    };
    return item;
  }

  getChildren(element) {
    if (!element) return this._groups;
    return element.pack ? element.tasks : [];
  }
}

async function pickTask() {
  const groups = tasksToTree(await run('listTasks'));
  const items = groups.flatMap((group) =>
    group.tasks.map((task) => ({
      label: task.id,
      description: [task.difficulty, task.runnable ? '' : 'not runnable here']
        .filter(Boolean)
        .join(' | '),
    })),
  );
  const chosen = await vscode.window.showQuickPick(items, { placeHolder: 'Task to run' });
  return chosen && chosen.label;
}

async function pickAgent() {
  const rows = await run('listAgents');
  const items = rows.map((row) => ({
    label: row.name,
    description: row.vision ? `vision: ${row.vision}` : '',
  }));
  const chosen = await vscode.window.showQuickPick(items, { placeHolder: 'Agent adapter' });
  return chosen && chosen.label;
}

async function pickBundle() {
  const found = await vscode.workspace.findFiles('**/*.tooltrace/manifest.json', null, 200);
  if (!found.length) {
    vscode.window.showInformationMessage('No .tooltrace bundles in this workspace.');
    return undefined;
  }
  const items = found.map((uri) => {
    const bundle = path.dirname(uri.fsPath);
    return { label: path.basename(bundle), description: bundle, bundle };
  });
  const chosen = await vscode.window.showQuickPick(items, { placeHolder: 'Bundle' });
  return chosen && chosen.bundle;
}

function activate(context) {
  const output = vscode.window.createOutputChannel('ToolTrace Bench');
  const tree = new TaskTreeProvider();

  const guard = (handler) => async (...args) => {
    try {
      await handler(...args);
    } catch (error) {
      vscode.window.showErrorMessage(error.message);
      output.appendLine(error.stack || error.message);
    }
  };

  context.subscriptions.push(
    output,
    vscode.window.registerTreeDataProvider('tooltraceTasks', tree),

    vscode.commands.registerCommand('tooltrace.refreshTasks', guard(() => tree.refresh())),

    vscode.commands.registerCommand(
      'tooltrace.runTask',
      guard(async (taskId) => {
        const task = taskId || (await pickTask());
        if (!task) return;
        const agent = await pickAgent();
        if (!agent) return;
        const payload = await vscode.window.withProgress(
          { location: vscode.ProgressLocation.Notification, title: `tooltrace run ${task}` },
          () => run('runTask', { task, agent }),
        );
        const verdict = describeRun(payload);
        output.appendLine(JSON.stringify(payload, null, 2));
        output.show(true);
        if (verdict.kind === 'fail') vscode.window.showWarningMessage(verdict.message);
        else vscode.window.showInformationMessage(verdict.message);
      }),
    ),

    vscode.commands.registerCommand(
      'tooltrace.openTrace',
      guard(async () => {
        const bundle = await pickBundle();
        if (!bundle) return;
        const payload = await run('openTrace', { bundle });
        const events = Array.isArray(payload) ? payload : payload.events || [];
        const panel = vscode.window.createWebviewPanel(
          'tooltraceTrace',
          path.basename(bundle),
          vscode.ViewColumn.Active,
          // No scripts, no local resources: the document is static HTML and the
          // CSP in it says so. A trace contains untrusted text by design.
          { enableScripts: false },
        );
        panel.webview.html = traceToHtml(events, path.basename(bundle));
      }),
    ),

    vscode.commands.registerCommand(
      'tooltrace.verifyBundle',
      guard(async () => {
        const bundle = await pickBundle();
        if (!bundle) return;
        const payload = await run('verifyBundle', { bundle });
        output.appendLine(JSON.stringify(payload, null, 2));
        output.show(true);
      }),
    ),

    vscode.commands.registerCommand(
      'tooltrace.lintPack',
      guard(async () => {
        const root = workspaceRoot();
        if (!root) {
          vscode.window.showInformationMessage('Open a folder to lint a pack in it.');
          return;
        }
        const picked = await vscode.window.showOpenDialog({
          canSelectFiles: false,
          canSelectFolders: true,
          defaultUri: vscode.Uri.file(root),
          openLabel: 'Lint this pack',
        });
        if (!picked || !picked.length) return;
        // `lint` exits 3 when it finds something, which is the point of it --
        // `run` does not gate on the exit code for exactly this reason.
        output.appendLine(JSON.stringify(await run('lintPack', { path: picked[0].fsPath }), null, 2));
        output.show(true);
      }),
    ),

    vscode.commands.registerCommand(
      'tooltrace.doctor',
      guard(async () => {
        output.appendLine(JSON.stringify(await run('doctor'), null, 2));
        output.show(true);
      }),
    ),
  );

  tree.refresh();
}

function deactivate() {}

module.exports = { activate, deactivate };
