/**
 * The console's rules are about what it refuses to do.
 *
 * Three of its four decisions are the opposite of the obvious one, and each
 * would look fine in a screenshot while being wrong in use:
 *
 * - a live region on a running sweep reads every frame aloud and interrupts
 *   itself, so announcing is off until a reader turns it on;
 * - a pause that closed the stream would miss what happened while paused and
 *   then resume looking continuous;
 * - a buffer that dropped its oldest entries silently would leave a reader
 *   scrolling to the top and believing they had reached the beginning.
 *
 * The pure functions are tested directly. The component's SSE path needs a
 * server, and this suite has none, so what is checked here is the parsing and
 * the wording -- the parts that would be wrong in production too.
 */

import { describe, expect, it } from 'vitest'
import { BUFFER, describeBuffer, parseFrame } from '../pages/workspace/console'

const AT = '2026-09-11T10:00:00.000Z'

describe('parsing a frame', () => {
  it('keeps the type, the id and whatever else came with it', () => {
    const event = parseFrame('{"type":"run_finished","id":"r1","status":"ok"}', 7, AT)
    expect(event).toMatchObject({ seq: 7, at: AT, type: 'run_finished', id: 'r1' })
    expect(event?.detail).toContain('ok')
  })

  it('survives a malformed frame instead of taking the console down', () => {
    // A bad frame is a fact about the server, and a console that died on one
    // would stop working exactly when somebody was most likely watching it.
    expect(parseFrame('not json at all', 0, AT)).toBeNull()
    expect(parseFrame('null', 0, AT)).toBeNull()
    expect(parseFrame('[1,2,3]', 0, AT)).toBeNull()
  })

  it('refuses a frame with no type, rather than rendering a blank row', () => {
    expect(parseFrame('{"id":"r1"}', 0, AT)).toBeNull()
  })

  it('tolerates a frame with a type and nothing else', () => {
    const event = parseFrame('{"type":"heartbeat"}', 1, AT)
    expect(event).toMatchObject({ type: 'heartbeat', id: '', detail: '' })
  })

  it('does not repeat the type and id inside the detail', () => {
    const event = parseFrame('{"type":"x","id":"y","extra":1}', 0, AT)
    expect(event?.detail).toBe('{"extra":1}')
  })
})

describe('what the buffer notice says', () => {
  it('says only the count when nothing was lost', () => {
    expect(describeBuffer(12, 0, 0)).toBe('12 events shown.')
  })

  it('names dropped events rather than hiding the truncation', () => {
    // Silently dropping leaves a reader scrolling to the top and believing they
    // reached the beginning.
    expect(describeBuffer(BUFFER, 40, 0)).toContain('40 older dropped')
  })

  it('says how many arrived while paused', () => {
    // Otherwise a resumed feed looks continuous across a gap.
    expect(describeBuffer(5, 0, 9)).toContain('9 arrived while paused')
  })

  it('gets the singular right', () => {
    expect(describeBuffer(1, 0, 0)).toBe('1 event shown.')
  })

  it('reports both losses at once when both happened', () => {
    const text = describeBuffer(BUFFER, 3, 4)
    expect(text).toContain('3 older dropped')
    expect(text).toContain('4 arrived while paused')
  })
})

describe('the buffer bound', () => {
  it('is bounded at all', () => {
    // An unbounded array in a tab left open overnight.
    expect(BUFFER).toBeGreaterThan(50)
    expect(BUFFER).toBeLessThanOrEqual(1000)
  })
})
