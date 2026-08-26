// DEMO fixtures for the self-hosted workspace console.
// These are synthetic examples that let people preview the team console
// without a server. They are ALWAYS rendered behind a "DEMO DATA" badge and
// never mixed into public dataset pages (those render only validated bundles).

import type { AuditRow, ApprovalRow, ExperimentRow } from '../api'

export const DEMO_EXPERIMENTS: ExperimentRow[] = [
  { id: 'exp-demo01a2b', status: 'completed', workspace_id: 'ws-demo', suite_id: 'fileops-core', agent_adapter: 'openai_compat', repetitions: 5, created_at: '2026-08-20T10:12:00Z' },
  { id: 'exp-demo03c4d', status: 'running', workspace_id: 'ws-demo', suite_id: 'recovery-chaos', agent_adapter: 'subprocess', repetitions: 3, created_at: '2026-08-25T09:40:00Z' },
  { id: 'exp-demo05e6f', status: 'queued', workspace_id: 'ws-demo', suite_id: 'mockapi-flow', agent_adapter: 'scripted', repetitions: 1, created_at: '2026-08-26T08:05:00Z' },
]

export interface DemoWorker {
  id: string
  os: string
  arch: string
  containers: string
  browser: string
  gpu: string
  status: 'idle' | 'busy' | 'offline'
  utilization: number
}

export const DEMO_WORKERS: DemoWorker[] = [
  { id: 'worker-lab-1', os: 'linux', arch: 'x86_64', containers: 'docker', browser: 'chromium', gpu: 'none', status: 'busy', utilization: 0.8 },
  { id: 'worker-lab-2', os: 'linux', arch: 'arm64', containers: 'podman', browser: 'none', gpu: 'none', status: 'idle', utilization: 0 },
  { id: 'worker-win-1', os: 'windows', arch: 'x86_64', containers: 'docker', browser: 'msedge', gpu: 'cuda-a100', status: 'idle', utilization: 0 },
  { id: 'worker-lab-3', os: 'linux', arch: 'x86_64', containers: 'none', browser: 'firefox', gpu: 'none', status: 'offline', utilization: 0 },
]

export const DEMO_APPROVALS: ApprovalRow[] = [
  { request_id: 'apr-demo12345', workspace_id: 'ws-demo', action: 'publish_results', state: 'pending', requested_by: 'alice' },
  { request_id: 'apr-demo67890', workspace_id: 'ws-demo', action: 'enable_networked_task', state: 'approved', requested_by: 'bob', decided_by: 'carol' },
  { request_id: 'apr-demobbbbb', workspace_id: 'ws-demo', action: 'change_shared_baseline', state: 'rejected', requested_by: 'dave', decided_by: 'carol' },
]

export const DEMO_AUDIT: AuditRow[] = [
  { seq: 41, actor: 'carol', action: 'approval.decide', target: 'apr-demo67890', at: '2026-08-26T07:58:00Z', prev_hash: 'a1…', hash: '9f2c…' },
  { seq: 40, actor: 'bob', action: 'approval.request', target: 'apr-demo67890', at: '2026-08-26T07:55:00Z', prev_hash: '77be…', hash: 'a1…' },
  { seq: 39, actor: 'alice', action: 'experiment.create', target: 'exp-demo03c4d', at: '2026-08-25T09:40:00Z', prev_hash: '03dd…', hash: '77be…' },
]

export interface DemoUser {
  user_id: string
  display_name: string
  role: string
  kind: 'human' | 'service_account'
}

export const DEMO_USERS: DemoUser[] = [
  { user_id: 'usr-alice', display_name: 'Alice (admin)', role: 'admin', kind: 'human' },
  { user_id: 'usr-bob', display_name: 'Bob', role: 'runner', kind: 'human' },
  { user_id: 'usr-carol', display_name: 'Carol', role: 'reviewer', kind: 'human' },
  { user_id: 'svc-ci-bot', display_name: 'CI regression bot', role: 'service_account', kind: 'service_account' },
]

export interface DemoBaseline {
  scope: string
  metric: string
  value: number
  tolerance: number
  last_updated: string
}

export const DEMO_BASELINES: DemoBaseline[] = [
  { scope: 'suite/fileops-core', metric: 'success_rate', value: 0.92, tolerance: 0.05, last_updated: '2026-08-18' },
  { scope: 'domain/file-editing', metric: 'pass^k(k=3)', value: 0.87, tolerance: 0.06, last_updated: '2026-08-18' },
  { scope: 'task/fileops/copy-and-rename', metric: 'wall_ms_p95', value: 41000, tolerance: 8000, last_updated: '2026-08-12' },
]

export const DEMO_WEBHOOKS = [
  { id: 'wh-demo-ci', url: 'https://ci.example.invalid/hooks/tooltrace', events: 'run.completed, regression.detected', status: 'healthy (DEMO)' },
]
