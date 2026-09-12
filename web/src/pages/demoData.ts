// DEMO fixtures for the self-hosted workspace console.
//
// Synthetic examples that let someone preview the team console without a
// server. Always rendered behind a "DEMO DATA" badge, always through
// `ConsoleData`, and never mixed into public dataset pages -- those render only
// validated bundles.
//
// **Every fixture is typed as the type the real API returns.** They were not:
// the baselines fixture had `scope`/`metric`/`tolerance` columns, the webhooks
// fixture had a health `status`, and the workers fixture had a `utilization`
// ratio -- none of which this product produces. A preview of features that do
// not exist is a sales mock, and somebody evaluating the console would have
// been choosing it for a tolerance field that was never going to appear.
//
// Typing them against `../api` is what stops that recurring: a fixture can only
// promise what the server can answer, and the compiler checks it.

import type {
  ApprovalRow,
  AuditEntry,
  BaselineRow,
  ConsoleUser,
  ExperimentRow,
  WebhookRow,
  WorkerRow,
} from '../api'

export const DEMO_EXPERIMENTS: ExperimentRow[] = [
  { id: 'exp-demo01a2b', status: 'completed', workspace_id: 'ws-demo', suite_id: 'fileops-core', agent_adapter: 'openai_compat', repetitions: 5, created_at: '2026-08-20T10:12:00Z' },
  { id: 'exp-demo03c4d', status: 'running', workspace_id: 'ws-demo', suite_id: 'recovery-chaos', agent_adapter: 'subprocess', repetitions: 3, created_at: '2026-08-25T09:40:00Z' },
  { id: 'exp-demo05e6f', status: 'queued', workspace_id: 'ws-demo', suite_id: 'mockapi-flow', agent_adapter: 'scripted', repetitions: 1, created_at: '2026-08-26T08:05:00Z' },
]

export const DEMO_WORKERS: WorkerRow[] = [
  {
    worker_id: 'server',
    os_name: 'Linux',
    arch: 'x86_64',
    python_version: '3.12.4',
    container_runtime: 'docker',
    browser: false,
    gpu: true,
    gpu_detection: 'found',
    gpu_names: ['NVIDIA A100-SXM4-40GB'],
    max_concurrency: 16,
    registered_at: '2026-08-26T08:00:00Z',
  },
]

export const DEMO_APPROVALS: ApprovalRow[] = [
  { request_id: 'apr-demo12345', workspace_id: 'ws-demo', action: 'publish_results', state: 'pending', requested_by: 'alice' },
  { request_id: 'apr-demo67890', workspace_id: 'ws-demo', action: 'enable_networked_task', state: 'approved', requested_by: 'bob', decided_by: 'carol' },
  { request_id: 'apr-demobbbbb', workspace_id: 'ws-demo', action: 'change_shared_baseline', state: 'rejected', requested_by: 'dave', decided_by: 'carol' },
]

export const DEMO_AUDIT: AuditEntry[] = [
  {
    seq: 2,
    timestamp: '2026-08-26T07:58:00Z',
    actor: 'carol',
    action: 'approval.decide',
    target: 'apr-demo67890',
    details: { approved: true },
    prev_hash: '77be6f1c9a2d4e8b',
    entry_hash: 'a1d4c7e09b3f5182',
  },
  {
    seq: 1,
    timestamp: '2026-08-26T07:55:00Z',
    actor: 'bob',
    action: 'approval.request',
    target: 'apr-demo67890',
    details: {},
    prev_hash: '03dd1b5a7c8e2f40',
    entry_hash: '77be6f1c9a2d4e8b',
  },
  {
    seq: 0,
    timestamp: '2026-08-25T09:40:00Z',
    actor: 'alice',
    action: 'experiment.create',
    target: 'exp-demo03c4d',
    details: {},
    prev_hash: 'genesis',
    entry_hash: '03dd1b5a7c8e2f40',
  },
]

export const DEMO_USERS: ConsoleUser[] = [
  { user_id: 'usr-alice', display_name: 'Alice', role: 'admin', workspace_id: 'ws-demo', kind: 'user' },
  { user_id: 'usr-bob', display_name: 'Bob', role: 'runner', workspace_id: 'ws-demo', kind: 'user' },
  { user_id: 'usr-carol', display_name: 'Carol', role: 'reviewer', workspace_id: 'ws-demo', kind: 'user' },
  { user_id: 'usr-dana', display_name: 'Dana', role: 'auditor', workspace_id: 'ws-demo', kind: 'user' },
  {
    user_id: 'svc-ci-bot',
    display_name: 'CI regression bot',
    role: 'service_account',
    workspace_id: 'ws-demo',
    kind: 'service_account',
  },
]

export const DEMO_BASELINES: BaselineRow[] = [
  { name: 'nightly', bundle: '/srv/tooltrace/runs/nightly-2026-08-18.tooltrace' },
  { name: 'release-0.3.0', bundle: '/srv/tooltrace/runs/release-0.3.0.tooltrace' },
]

export const DEMO_WEBHOOKS: WebhookRow[] = [
  { url: 'https://ci.example.invalid/hooks/tooltrace', events: ['run.completed', 'regression.detected'] },
]
