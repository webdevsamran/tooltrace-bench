/**
 * Motion has to degrade correctly, not merely fail to crash.
 *
 * Every primitive in `motion.tsx` has two paths: the animated one, and the one
 * taken by a browser without the API or a reader who asked for less movement.
 * The second path is the one that gets shipped broken, because nobody develops
 * in it -- so it is the one tested hardest here.
 *
 * The animated path is mostly *not* asserted frame by frame. A test that
 * pinned the easing curve would fail on a design tweak that harmed nobody, and
 * would still not tell you whether the number came to rest on the right value.
 * What is asserted is the part a user could be misled by: the final value, the
 * announced value, and whether the route actually changed.
 */

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  Counter,
  MAX_TOASTS,
  ToastProvider,
  supportsViewTransitions,
  useToast,
  useViewTransition,
} from '../motion'

function setReducedMotion(reduced: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: reduced && query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

/**
 * Install a `startViewTransition` stub.
 *
 * Cast through `unknown` on purpose: `ViewTransition` is a wide interface, and
 * satisfying it properly would mean writing a fake browser. What is under test
 * is whether the hook calls it, not what it returns.
 */
function stubViewTransitions(start: (cb: () => void) => unknown) {
  Object.defineProperty(document, 'startViewTransition', {
    configurable: true,
    writable: true,
    value: start,
  })
}

afterEach(() => {
  setReducedMotion(false)
  Reflect.deleteProperty(document, 'startViewTransition')
  vi.restoreAllMocks()
})

// --- route transitions ------------------------------------------------------

function Routed() {
  const rendered = useViewTransition()
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate('/second')}>
        Go
      </button>
      <Routes location={rendered}>
        <Route path="/" element={<p>first page</p>} />
        <Route path="/second" element={<p>second page</p>} />
      </Routes>
    </>
  )
}

describe('view transitions', () => {
  it('still changes route when the browser has no View Transitions API', async () => {
    // Firefox, and every Safari before 18. A hook that assumed the API would
    // leave the route frozen on the previous page, which is worse than no
    // animation at all.
    expect(supportsViewTransitions()).toBe(false)
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routed />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(await screen.findByText('second page')).toBeInTheDocument()
  })

  it('uses the API when it is there', async () => {
    const start = vi.fn((cb: () => void) => {
      cb()
      return { skipTransition: vi.fn() }
    })
    stubViewTransitions(start)
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routed />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(await screen.findByText('second page')).toBeInTheDocument()
    expect(start).toHaveBeenCalled()
  })

  it('does not animate for a reader who asked for reduced motion', async () => {
    const start = vi.fn((cb: () => void) => {
      cb()
      return {}
    })
    stubViewTransitions(start)
    setReducedMotion(true)
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routed />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(await screen.findByText('second page')).toBeInTheDocument()
    expect(start).not.toHaveBeenCalled()
  })
})

// --- toasts -----------------------------------------------------------------

function Pusher({ count, message = 'Saved' }: { count: number; message?: string }) {
  const { push } = useToast()
  return (
    <button type="button" onClick={() => Array.from({ length: count }, (_, i) => push(`${message} ${i + 1}`))}>
      Push
    </button>
  )
}

describe('toasts', () => {
  it('stacks, rather than replacing the previous message', async () => {
    render(
      <ToastProvider>
        <Pusher count={3} />
      </ToastProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Push' }))
    expect(screen.getByText('Saved 1')).toBeInTheDocument()
    expect(screen.getByText('Saved 3')).toBeInTheDocument()
  })

  it('caps the stack so a loop cannot cover the page', async () => {
    render(
      <ToastProvider>
        <Pusher count={MAX_TOASTS + 6} />
      </ToastProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Push' }))
    const region = screen.getByRole('status', { name: 'Notifications' })
    expect(region.querySelectorAll('.toast')).toHaveLength(MAX_TOASTS)
  })

  it('announces through a live region that exists before the message does', () => {
    // A live region inserted at the same moment as its content is not announced
    // by most screen readers, so an empty one has to be in the tree already.
    render(
      <ToastProvider>
        <p>nothing yet</p>
      </ToastProvider>,
    )
    const region = screen.getByRole('status', { name: 'Notifications' })
    expect(region).toHaveAttribute('aria-live', 'polite')
  })

  it('is dismissible, by a name that says which one', async () => {
    render(
      <ToastProvider>
        <Pusher count={1} message="Copied" />
      </ToastProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Push' }))
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss: Copied 1' }))
    await waitFor(() => expect(screen.queryByText('Copied 1')).not.toBeInTheDocument())
  })

  it('drops the message rather than crashing outside a provider', async () => {
    // A page rendered on its own, in a test or a future embed, should not throw
    // because a confirmation had nowhere to go.
    render(<Pusher count={1} />)
    await userEvent.click(screen.getByRole('button', { name: 'Push' }))
    expect(screen.queryByText('Saved 1')).not.toBeInTheDocument()
  })
})

// --- rolling numbers --------------------------------------------------------

describe('counters', () => {
  it('reads as the true value to a screen reader, not the animating one', () => {
    // Sixty announcements to say one number, of which only the last is true.
    render(<Counter value={87} format={(n) => `${n.toFixed(0)}%`} />)
    expect(screen.getByText('87%', { selector: '.sr-only' })).toBeInTheDocument()
  })

  it('lands exactly on the target', async () => {
    // An eased counter that approaches asymptotically settles at 99.97 when the
    // number is 100, and then renders a wrong pass rate forever.
    const { rerender, container } = render(<Counter value={0} format={(n) => n.toFixed(2)} />)
    rerender(<Counter value={100} format={(n) => n.toFixed(2)} />)
    await waitFor(
      () => {
        const visible = container.querySelector('[aria-hidden="true"]')
        expect(visible?.textContent).toBe('100.00')
      },
      { timeout: 3000 },
    )
  })

  it('jumps straight to the value under reduced motion', () => {
    setReducedMotion(true)
    const { rerender, container } = render(<Counter value={0} />)
    act(() => {
      rerender(<Counter value={42} />)
    })
    expect(container.querySelector('[aria-hidden="true"]')?.textContent).toBe('42')
  })
})
