/**
 * The live run console: a server-sent event feed you can leave open.
 *
 * The feed already existed as a twenty-line card inside the Experiments page,
 * rendering `type:id` strings. That is a progress indicator, not a console —
 * and the information architecture asks for a console, which is a different
 * thing: somewhere you can leave open on a second monitor while working
 * elsewhere, pause to read, and scroll back through.
 *
 * Three decisions worth stating, because each is the opposite of the obvious
 * one:
 *
 * **The log does not announce by default.** A live region attached to a
 * firehose is unusable: a screen reader would read every frame of a running
 * sweep aloud, interrupting itself, and the reader would learn nothing. So the
 * feed is `role="log"` with `aria-live="off"`, and announcing is a checkbox the
 * reader turns on when they want it. An accessibility feature that makes the
 * page unusable is not an accessibility feature.
 *
 * **The buffer is capped and says so.** Keeping every event of a long sweep is
 * an unbounded array in a tab somebody left open overnight. Dropping the oldest
 * silently would leave a reader scrolling to the top and believing they had
 * reached the beginning, so the count of dropped events is on screen.
 *
 * **Pausing stops rendering, not receiving.** A pause that closed the stream
 * would silently miss what happened while it was paused, and the feed would
 * resume looking continuous. Events keep arriving into the buffer; only the
 * view is frozen, and it says how many arrived while it was.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { isServerMode, subscribeEvents } from '../../api'
import { EmptyState } from '../../components'
import { ServerGate, ServerStatus } from './shared'

/**
 * How many events are kept. Roughly a screen and a half of scrollback at any
 * plausible row height, and bounded so a tab left open overnight does not grow
 * without limit.
 */
export const BUFFER = 200

export interface ConsoleEvent {
  seq: number
  at: string
  type: string
  id: string
  detail: string
}

/**
 * One SSE frame, parsed defensively.
 *
 * Returns null rather than throwing on anything unexpected. A malformed frame
 * is a fact about the server, and a console that died on one would be a console
 * that stopped working exactly when something had gone wrong upstream — which
 * is when somebody is most likely to be watching it.
 */
export function parseFrame(data: string, seq: number, at: string): ConsoleEvent | null {
  try {
    const parsed: unknown = JSON.parse(data)
    if (!parsed || typeof parsed !== 'object') return null
    const record = parsed as Record<string, unknown>
    const type = typeof record.type === 'string' ? record.type : ''
    if (!type) return null
    const { type: _t, id: _i, ...rest } = record
    return {
      seq,
      at,
      type,
      id: typeof record.id === 'string' ? record.id : '',
      detail: Object.keys(rest).length ? JSON.stringify(rest) : '',
    }
  } catch {
    return null
  }
}

/** What the buffer notice says. Counts, never "some". */
export function describeBuffer(shown: number, dropped: number, paused: number): string {
  const parts = [`${shown} event${shown === 1 ? '' : 's'} shown`]
  if (dropped > 0) parts.push(`${dropped} older dropped`)
  if (paused > 0) parts.push(`${paused} arrived while paused`)
  return `${parts.join('; ')}.`
}

export function LiveConsolePage() {
  const [events, setEvents] = useState<ConsoleEvent[]>([])
  const [dropped, setDropped] = useState(0)
  const [paused, setPaused] = useState(false)
  const [pausedCount, setPausedCount] = useState(0)
  const [announce, setAnnounce] = useState(false)
  const [filter, setFilter] = useState('')
  const seq = useRef(0)
  // Read inside the subscription callback, which is created once: a `paused`
  // captured in the closure would freeze at its initial value and the pause
  // button would do nothing after the first render.
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  useEffect(() => {
    if (!isServerMode()) return undefined
    const off = subscribeEvents((message: MessageEvent) => {
      const event = parseFrame(String(message.data), seq.current++, new Date().toISOString())
      if (!event) return
      if (pausedRef.current) {
        // Still received, deliberately. Closing the stream would miss what
        // happened while paused and then resume looking continuous.
        setPausedCount((n) => n + 1)
        return
      }
      setEvents((current) => {
        const next = [event, ...current]
        if (next.length > BUFFER) setDropped((n) => n + next.length - BUFFER)
        return next.slice(0, BUFFER)
      })
    })
    return off
  }, [])

  const resume = useCallback(() => {
    setPaused(false)
    setPausedCount(0)
  }, [])

  const shown = useMemo(() => {
    if (!filter) return events
    const needle = filter.toLowerCase()
    return events.filter((e) =>
      `${e.type} ${e.id} ${e.detail}`.toLowerCase().includes(needle),
    )
  }, [events, filter])

  return (
    <ServerGate>
      <section>
        <h1>Live console</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            Server-sent events from this ToolTrace server, newest first. Nothing is stored: this is
            the stream, not a log you can come back to.
          </span>
        </p>

        <div className="console-controls">
          <button
            type="button"
            className="btn"
            onClick={() => (paused ? resume() : setPaused(true))}
          >
            {paused ? 'Resume' : 'Pause'}
          </button>
          <input
            className="search"
            type="search"
            placeholder="Filter by type, id or payload…"
            aria-label="Filter events"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <label className="console-announce">
            <input
              type="checkbox"
              checked={announce}
              onChange={(e) => setAnnounce(e.target.checked)}
            />
            {/* Off by default, and the reason is in the label rather than in a
                comment nobody reading the page can see. */}
            <span>
              Announce new events <span className="muted">(off: a busy stream is unreadable)</span>
            </span>
          </label>
        </div>

        <p className="muted" role="status" aria-live="polite" aria-label="Console buffer">
          {describeBuffer(shown.length, dropped, pausedCount)}
        </p>

        {events.length === 0 ? (
          <EmptyState hint="No events yet. This console shows activity as it happens; start a run to see it." />
        ) : (
          <ul
            className="console-log"
            // `log` is the role for a feed of appended records. The live
            // setting is a choice the reader makes, not one made for them.
            role="log"
            aria-label="Event stream"
            aria-live={announce ? 'polite' : 'off'}
          >
            {shown.map((event) => (
              <li key={event.seq} className="console-row">
                <time dateTime={event.at} className="console-at">
                  {event.at.slice(11, 19)}
                </time>
                <span className="console-type">{event.type}</span>
                <span className="console-id">{event.id}</span>
                {event.detail && <span className="console-detail">{event.detail}</span>}
              </li>
            ))}
          </ul>
        )}

        {shown.length === 0 && events.length > 0 && (
          <p className="state empty">No event in the buffer matches that filter.</p>
        )}
      </section>
    </ServerGate>
  )
}
