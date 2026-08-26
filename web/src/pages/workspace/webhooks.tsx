// HMAC-signed webhooks / integration targets view.

import { isServerMode } from '../../api'
import { DataTable, DemoBadge, type Column } from '../../components'
import { DEMO_WEBHOOKS } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

interface WebhookDisplay {
  id: string
  url: string
  events: string
  status: string
}

const WEBHOOK_COLS: Column<WebhookDisplay>[] = [
  { key: 'id', header: 'ID', value: (w) => w.id },
  { key: 'url', header: 'Endpoint', value: (w) => w.url },
  { key: 'events', header: 'Events', value: (w) => w.events },
  { key: 'status', header: 'Delivery status', value: (w) => w.status },
]

export function WebhooksPage() {
  return (
    <ServerGate>
      <section>
        <h1>Webhooks & integrations</h1>
        <p>
          <ServerStatus /> <span className="muted">
            Deliveries are HMAC-SHA256 signed with retries and backoff. Email/Slack-compatible targets are
            generic webhook receivers — vendor secrets never enter core benchmark data.
          </span>
        </p>
        {!isServerMode() && <DemoBadge />}
        <DataTable rows={DEMO_WEBHOOKS} columns={WEBHOOK_COLS} emptyHint="No webhooks registered." />
      </section>
    </ServerGate>
  )
}
