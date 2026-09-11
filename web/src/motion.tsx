/**
 * The four interaction primitives the design spec asks for, and the honesty
 * rules each of them has to obey.
 *
 * Motion is the part of a UI that is easiest to add and easiest to get wrong,
 * and the failure is always the same shape: the animation becomes the source of
 * truth. A counter that rolls toward 100 and stops at 99.97 is lying about the
 * number. A toast that slides in is a message a screen-reader user never hears.
 * A route transition that needs `document.startViewTransition` is a blank page
 * in Firefox. A brush you can only draw with a mouse is a filter a keyboard
 * user cannot reach -- and axe is a CI gate in this repository, so that is a
 * broken build rather than a regrettable omission.
 *
 * So every primitive here has a degraded path that is *correct*, not merely
 * non-crashing, and `prefers-reduced-motion` collapses each to an instant state
 * change rather than to a faster animation.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { flushSync } from 'react-dom'
import { useLocation, type Location } from 'react-router-dom'

/** Durations from the design spec: 120ms micro, 200ms local, 320ms route. */
export const DURATION = { micro: 120, local: 200, route: 320 } as const

/**
 * Read live rather than cached.
 *
 * The OS setting can change while the page is open, and a value captured at
 * module load would keep animating for someone who had just asked it to stop.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// --- route transitions ------------------------------------------------------

export function supportsViewTransitions(): boolean {
  return (
    typeof document !== 'undefined' &&
    typeof (document as Document & { startViewTransition?: unknown }).startViewTransition ===
      'function'
  )
}

/**
 * The location to render, one transition behind the router when it can be.
 *
 * The View Transitions API captures the old DOM, applies the update, and
 * cross-fades. That only works if the update happens *synchronously inside* the
 * callback, which is why `flushSync` is here: React would otherwise batch the
 * state change to after the snapshot and the transition would cross-fade a
 * frame with itself.
 *
 * Two reasons this returns the new location immediately instead:
 *
 * - **No support.** Firefox has no `startViewTransition`, and a hook that
 *   assumed it would leave the route frozen on the previous page -- a worse
 *   outcome than no animation at all.
 * - **Reduced motion.** A cross-fade is motion. The spec says every animation
 *   collapses to an instant state change, and this is the one with the largest
 *   moving area on screen.
 */
export function useViewTransition(): Location {
  const location = useLocation()
  const [rendered, setRendered] = useState(location)
  const pending = useRef<{ skipTransition?: () => void } | null>(null)

  useEffect(() => {
    if (rendered.key === location.key) return undefined
    if (!supportsViewTransitions() || prefersReducedMotion()) {
      setRendered(location)
      return undefined
    }
    // A navigation during a transition supersedes it. Without this the second
    // route waits for the first cross-fade, which reads as a dropped click.
    pending.current?.skipTransition?.()
    const start = (document as Document & {
      startViewTransition: (cb: () => void) => { skipTransition?: () => void }
    }).startViewTransition
    pending.current = start.call(document, () => {
      flushSync(() => setRendered(location))
    })
    return undefined
  }, [location, rendered.key])

  return rendered
}

// --- toasts -----------------------------------------------------------------

export type ToastKind = 'info' | 'ok' | 'warn' | 'bad'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

/**
 * How many toasts are kept on screen at once.
 *
 * A stack is the point -- the spec asks for stacking -- but an unbounded one is
 * a full-screen overlay the moment anything loops. The oldest is dropped, and
 * the live region still announced it, so nothing is lost to a reader who was
 * listening.
 */
export const MAX_TOASTS = 4

/** How long a toast stays before dismissing itself, in milliseconds. */
export const TOAST_LIFETIME = 6000

interface ToastApi {
  toasts: Toast[]
  push: (message: string, kind?: ToastKind) => number
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastApi | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
    setToasts((current) => current.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (message: string, kind: ToastKind = 'info') => {
      const id = nextId.current++
      setToasts((current) => [...current, { id, kind, message }].slice(-MAX_TOASTS))
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), TOAST_LIFETIME),
      )
      return id
    },
    [dismiss],
  )

  // Timers outlive the component otherwise, and fire `setToasts` on an
  // unmounted tree -- which in a test run shows up as a warning from whichever
  // test happened to be running at the time.
  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach((timer) => clearTimeout(timer))
      pending.clear()
    }
  }, [])

  const api = useMemo(() => ({ toasts, push, dismiss }), [toasts, push, dismiss])
  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastRegion toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

/**
 * Outside a provider this is a no-op rather than a throw.
 *
 * A page rendered on its own in a test, or mounted by a future embed, should
 * not crash because a confirmation had nowhere to go. The message is dropped;
 * nothing else is.
 */
export function useToast(): ToastApi {
  const api = useContext(ToastContext)
  return (
    api ?? {
      toasts: [],
      push: () => -1,
      dismiss: () => {},
    }
  )
}

function ToastRegion({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    // `role="status"` with `aria-live="polite"` rather than `alert`: these are
    // confirmations, and an assertive region interrupts whatever the reader was
    // in the middle of. The region exists even when empty, because a live
    // region added to the page at the same time as its content is not announced
    // by most screen readers.
    <div className="toast-region" role="status" aria-live="polite" aria-label="Notifications">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.kind}`}>
          <span className="toast-message">{toast.message}</span>
          <button
            type="button"
            className="toast-dismiss"
            onClick={() => onDismiss(toast.id)}
            aria-label={`Dismiss: ${toast.message}`}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      ))}
    </div>
  )
}

// --- rolling numbers --------------------------------------------------------

/**
 * Interpolate toward `value`, and **land on it exactly**.
 *
 * The last frame is assigned rather than interpolated. An eased counter that
 * approaches its target asymptotically settles at 99.97 when the number is 100,
 * and a benchmark dashboard that renders a pass rate slightly wrong forever is
 * worse than one that renders it instantly.
 *
 * Returns the target immediately under reduced motion, and when the tab is
 * hidden -- `requestAnimationFrame` does not run in a background tab, so a
 * counter started there would otherwise sit at its old value until the user
 * came back and looked at a stale number.
 */
export function useCountUp(value: number, durationMs: number = DURATION.local): number {
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  const frame = useRef(0)

  useEffect(() => {
    if (shown === value) return undefined
    if (
      prefersReducedMotion() ||
      typeof requestAnimationFrame !== 'function' ||
      (typeof document !== 'undefined' && document.hidden)
    ) {
      setShown(value)
      return undefined
    }
    // The start time comes from the first frame, not from `performance.now()`.
    // `requestAnimationFrame` passes a timestamp on its own clock, and the two
    // do not share an origin -- in jsdom they were ten seconds apart, which
    // drove `t` to -51 and rendered the counter at -14,405,375 on its way to
    // 100. A browser with a `timeOrigin` offset would do the same thing more
    // quietly.
    let start = 0
    const origin = from.current
    const step = (now: number) => {
      if (!start) start = now
      const t = Math.min(1, (now - start) / durationMs)
      // cubic-bezier(.2,.8,.2,1) is the spec's easing; this is its ease-out
      // shape, which is what a viewer reads as "settling".
      const eased = 1 - (1 - t) ** 3
      if (t >= 1) {
        setShown(value)
        from.current = value
        return
      }
      setShown(origin + (value - origin) * eased)
      frame.current = requestAnimationFrame(step)
    }
    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
    // `shown` is deliberately not a dependency: including it restarts the
    // animation on every frame it produces.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, durationMs])

  useEffect(() => {
    from.current = shown
  }, [shown])

  return shown
}

/**
 * A number that rolls when it changes, and reads as its final value.
 *
 * The animating text is `aria-hidden`; the accessible name is the target. A
 * live counter that announced every frame would read a screen-reader user
 * sixty numbers to say one, and only the last of them would be true.
 */
export function Counter({
  value,
  format = (n: number) => n.toFixed(0),
  className,
}: {
  value: number
  format?: (n: number) => string
  className?: string
}) {
  const shown = useCountUp(value)
  return (
    <span className={className}>
      <span aria-hidden="true">{format(shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  )
}
