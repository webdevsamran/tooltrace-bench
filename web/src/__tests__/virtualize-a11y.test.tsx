import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DiffViewer, TraceTimeline, type TraceLine } from '../components'

const events = (n: number): TraceLine[] =>
  Array.from({ length: n }, (_, i) => ({
    seq: i,
    type: 'tool_result',
    tool: 'read_file',
    status: i % 7 === 0 ? 'error' : 'ok',
    duration_ms: 1.5,
    summary: `event ${i}`,
  }))

describe('TraceTimeline virtualization', () => {
  it('renders every row for a short trace', () => {
    render(<TraceTimeline events={events(20)} />)
    expect(screen.getAllByRole('option')).toHaveLength(20)
  })

  it('renders only a window for a long trace', () => {
    // The point of the change: 5000 events must not become 5000 DOM nodes.
    render(<TraceTimeline events={events(5000)} />)
    const rendered = screen.getAllByRole('option').length
    expect(rendered).toBeGreaterThan(0)
    expect(rendered).toBeLessThan(100)
  })

  it('still reports the full size to assistive technology', () => {
    // A screen reader must be told there are 5000 events even though only a
    // window exists in the DOM, or virtualization silently loses information.
    render(<TraceTimeline events={events(5000)} />)
    const list = screen.getByRole('listbox')
    expect(list).toHaveAccessibleName(/5000 events/)
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-setsize', '5000')
  })

  it('is reachable and navigable by keyboard', () => {
    render(<TraceTimeline events={events(5000)} />)
    const list = screen.getByRole('listbox')
    expect(list).toHaveAttribute('tabIndex', '0')
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    expect(screen.getAllByRole('option').some((o) => o.getAttribute('aria-selected') === 'true')).toBe(true)
  })

  it('End jumps to the last event without a thousand key presses', () => {
    render(<TraceTimeline events={events(5000)} />)
    const list = screen.getByRole('listbox')
    fireEvent.keyDown(list, { key: 'End' })
    expect(list.scrollTop).toBeGreaterThan(0)
  })
})

describe('DiffViewer accessibility', () => {
  const diff = ['--- a', '+++ b', '@@ -1 +1 @@', '-timout = 30', '+timeout = 30'].join('\n')

  it('is a named region so it can be found', () => {
    render(<DiffViewer diff={diff} />)
    expect(screen.getByRole('region')).toHaveAccessibleName(/1 lines added, 1 removed/)
  })

  it('is focusable, so it can be scrolled without a mouse', () => {
    render(<DiffViewer diff={diff} />)
    expect(screen.getByRole('region')).toHaveAttribute('tabIndex', '0')
  })

  it('labels added and removed lines rather than leaving bare punctuation', () => {
    render(<DiffViewer diff={diff} />)
    expect(screen.getByLabelText('added: timeout = 30')).toBeInTheDocument()
    expect(screen.getByLabelText('removed: timout = 30')).toBeInTheDocument()
  })

  it('shows an empty state rather than a blank box', () => {
    render(<DiffViewer diff="   " />)
    expect(screen.queryByRole('region')).toBeNull()
  })
})
