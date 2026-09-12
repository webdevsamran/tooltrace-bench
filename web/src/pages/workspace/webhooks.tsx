// Outbound webhook subscriptions.

import { listWebhooks, type WebhookRow } from '../../api'
import { type Column } from '../../components'
import { DEMO_WEBHOOKS } from '../demoData'
import { ConsoleData, ServerGate, ServerStatus } from './shared'

const HOOK_COLS: Column<WebhookRow>[] = [
  { key: 'url', header: 'Endpoint', value: (w) => w.url },
  { key: 'events', header: 'Events', value: (w) => w.events.join(', ') },
]

export function WebhooksPage() {
  return (
    <ServerGate>
      <section>
        <h1>Webhooks</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            Deliveries are signed with HMAC-SHA256 in <code>X-ToolTrace-Signature</code> and retried
            on a non-2xx response. <strong>The signing secret is never returned by the API</strong>:
            it is the only thing that makes a delivery verifiable, and a read endpoint that handed
            it out would let any viewer forge one.
          </span>
        </p>
        <ConsoleData
          load={listWebhooks}
          demo={DEMO_WEBHOOKS}
          columns={HOOK_COLS}
          emptyHint="No endpoints subscribed."
        />
      </section>
    </ServerGate>
  )
}
