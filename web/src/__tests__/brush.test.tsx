/**
 * A brush is a filter, so the rules are the filter's rules, not an animation's.
 *
 * Two properties matter more than the geometry:
 *
 * 1. **It is reachable from the keyboard.** `npm run test:e2e` runs axe as a
 *    gate here, and WCAG 2.2 AA requires that anything a pointer can do a
 *    keyboard can do. A drag-only brush is a filter half the users of this
 *    dashboard cannot operate.
 * 2. **It reports, it does not hide.** A chart that quietly dropped the points
 *    outside the range would leave a reader looking at a subset believing it
 *    was the whole — the same defect as reading a shard's pass rate as the
 *    sweep's.
 *
 * The geometry is still tested, because an up-and-left drag selecting nothing
 * is a bug half of all users hit on their first try.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import {
  BrushControls,
  describeBrush,
  isEmptyRange,
  normalizeRange,
  withinBrush,
  type BrushRange,
} from '../brush'

const BOUNDS: BrushRange = { x0: 0, x1: 10, y0: 0, y1: 1 }

describe('range geometry', () => {
  it('accepts a drag in any direction', () => {
    const downRight = normalizeRange({ x: 1, y: 0.2 }, { x: 4, y: 0.8 })
    const upLeft = normalizeRange({ x: 4, y: 0.8 }, { x: 1, y: 0.2 })
    expect(upLeft).toEqual(downRight)
    expect(downRight).toEqual({ x0: 1, x1: 4, y0: 0.2, y1: 0.8 })
  })

  it('includes a point sitting exactly on the edge the user drew', () => {
    const brush = { x0: 1, x1: 4, y0: 0.2, y1: 0.8 }
    expect(withinBrush({ x: 1, y: 0.2 }, brush)).toBe(true)
    expect(withinBrush({ x: 4, y: 0.8 }, brush)).toBe(true)
    expect(withinBrush({ x: 4.01, y: 0.8 }, brush)).toBe(false)
  })

  it('treats no range as everything, not as nothing', () => {
    // The difference between "no filter" and "a filter matching zero points".
    expect(withinBrush({ x: 99, y: 99 }, null)).toBe(true)
  })

  it('treats a click with no drag as no range', () => {
    // A stray click would otherwise blank the chart.
    expect(isEmptyRange(normalizeRange({ x: 2, y: 0.5 }, { x: 2, y: 0.5 }))).toBe(true)
    expect(isEmptyRange({ x0: 1, x1: 4, y0: 0.2, y1: 0.8 })).toBe(false)
    expect(isEmptyRange(null)).toBe(true)
  })
})

describe('what the reader is told', () => {
  it('names counts rather than adjectives', () => {
    expect(describeBrush(3, 12, { x0: 1, x1: 4, y0: 0.2, y1: 0.8 })).toBe(
      '3 of 12 in the selected range.',
    )
  })

  it('says the whole set is showing when nothing is selected', () => {
    // Never silence: a reader who cannot see the rectangle needs to know
    // whether they are looking at everything.
    expect(describeBrush(12, 12, null)).toBe('No range selected; showing all 12.')
  })
})

describe('the keyboard route', () => {
  it('sets the same range a drag would, with native controls', async () => {
    const onChange = vi.fn()
    render(
      <BrushControls
        brush={null}
        bounds={BOUNDS}
        onChange={onChange}
        xLabel="cost"
        yLabel="accuracy"
      />,
    )
    const min = screen.getByLabelText('Min cost')
    await userEvent.clear(min)
    await userEvent.type(min, '2')
    expect(onChange).toHaveBeenCalled()
    expect(onChange.mock.calls.at(-1)?.[0]).toMatchObject({ x0: 2 })
  })

  it('exposes all four edges, so any range is reachable without a mouse', () => {
    render(
      <BrushControls
        brush={null}
        bounds={BOUNDS}
        onChange={() => {}}
        xLabel="cost"
        yLabel="accuracy"
      />,
    )
    for (const label of ['Min cost', 'Max cost', 'Min accuracy', 'Max accuracy']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    }
  })

  it('clears back to no range rather than to the bounds', async () => {
    // Clearing to the bounds looks identical and is not the same thing: the
    // live region would then say "12 of 12 in the selected range" forever.
    const onChange = vi.fn()
    render(
      <BrushControls
        brush={{ x0: 1, x1: 4, y0: 0.2, y1: 0.8 }}
        bounds={BOUNDS}
        onChange={onChange}
        xLabel="cost"
        yLabel="accuracy"
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Clear range' }))
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('shows the bounds when nothing is selected, so the inputs are not empty', () => {
    render(
      <BrushControls
        brush={null}
        bounds={BOUNDS}
        onChange={() => {}}
        xLabel="cost"
        yLabel="accuracy"
      />,
    )
    expect(screen.getByLabelText('Max accuracy')).toHaveValue(1)
  })
})
