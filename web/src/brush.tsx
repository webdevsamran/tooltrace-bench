/**
 * Drag a rectangle on a chart to select a range — and reach the same range
 * from the keyboard, because otherwise it is not a feature, it is a barrier.
 *
 * A brush is the one micro-interaction in the design spec that carries real
 * information: it is a filter, so anyone who cannot draw it cannot use the
 * chart. `npm run test:e2e` runs axe as a gate in this repository, and WCAG 2.2
 * AA is explicit that functionality available by pointer must be available by
 * keyboard. So the drag is a *second* way to set a range that four number
 * inputs already set, rather than the only way.
 *
 * The other rule: **the chart reports the selection, it does not apply it.**
 * A brush that silently filtered the data would leave a reader looking at a
 * subset believing it was the whole, which is the same defect as a benchmark
 * reporting a shard's rate as the sweep's.
 *
 * Geometry lives in data space, not pixels. A brush stored as a screen
 * rectangle stops meaning anything the moment the container resizes, and this
 * dashboard is specified down to 360px.
 */

import { useCallback, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

export interface BrushRange {
  x0: number
  x1: number
  y0: number
  y1: number
}

export interface BrushPoint {
  x: number
  y: number
}

/**
 * Two corners in any order become a range with `x0 <= x1` and `y0 <= y1`.
 *
 * Dragging up-and-left is as natural as down-and-right, and an implementation
 * that only handled one produced an empty selection for half its users.
 */
export function normalizeRange(a: BrushPoint, b: BrushPoint): BrushRange {
  return {
    x0: Math.min(a.x, b.x),
    x1: Math.max(a.x, b.x),
    y0: Math.min(a.y, b.y),
    y1: Math.max(a.y, b.y),
  }
}

/** Inclusive on both edges: a point exactly on the line the user drew is in. */
export function withinBrush(point: BrushPoint, brush: BrushRange | null): boolean {
  if (!brush) return true
  return point.x >= brush.x0 && point.x <= brush.x1 && point.y >= brush.y0 && point.y <= brush.y1
}

/**
 * A range with no area selects nothing, and that has to be distinguishable
 * from no range at all.
 *
 * A click without a drag produces a zero-area rectangle. Treating that as "no
 * filter" is right -- the user did not mean to select nothing -- but treating
 * it as a filter matching zero points would blank the chart on a stray click.
 */
export function isEmptyRange(brush: BrushRange | null): boolean {
  return !brush || brush.x1 <= brush.x0 || brush.y1 <= brush.y0
}

/** What the live region says. Counts, not adjectives. */
export function describeBrush(inside: number, total: number, brush: BrushRange | null): string {
  if (isEmptyRange(brush)) return `No range selected; showing all ${total}.`
  return `${inside} of ${total} in the selected range.`
}

export interface BrushScale {
  /** Data value -> pixel, for both axes. */
  toPixelX: (value: number) => number
  toPixelY: (value: number) => number
  /** Pixel -> data value, for both axes. */
  toDataX: (pixel: number) => number
  toDataY: (pixel: number) => number
}

interface BrushState {
  brush: BrushRange | null
  dragging: BrushRange | null
  onPointerDown: (event: ReactPointerEvent<SVGElement>) => void
  onPointerMove: (event: ReactPointerEvent<SVGElement>) => void
  onPointerUp: (event: ReactPointerEvent<SVGElement>) => void
  clear: () => void
}

/**
 * Pointer handling for a brush over an SVG plot.
 *
 * Coordinates come from `getBoundingClientRect` and the viewBox, because an
 * SVG scaled with `width: 100%` has client pixels that are not user units, and
 * using the event's `offsetX` directly puts the rectangle somewhere else at
 * every window size but one.
 */
export function useBrush(
  scale: BrushScale,
  viewBoxWidth: number,
  viewBoxHeight: number,
  onChange?: (brush: BrushRange | null) => void,
): BrushState {
  const [brush, setBrush] = useState<BrushRange | null>(null)
  const [dragging, setDragging] = useState<BrushRange | null>(null)
  const origin = useRef<BrushPoint | null>(null)

  const toData = useCallback(
    (event: ReactPointerEvent<SVGElement>): BrushPoint => {
      const svg = event.currentTarget.ownerSVGElement ?? (event.currentTarget as SVGSVGElement)
      const rect = svg.getBoundingClientRect()
      const px = ((event.clientX - rect.left) / (rect.width || 1)) * viewBoxWidth
      const py = ((event.clientY - rect.top) / (rect.height || 1)) * viewBoxHeight
      return { x: scale.toDataX(px), y: scale.toDataY(py) }
    },
    [scale, viewBoxWidth, viewBoxHeight],
  )

  const onPointerDown = useCallback(
    (event: ReactPointerEvent<SVGElement>) => {
      // Primary button only: a right-click opens a context menu, and starting a
      // drag underneath it leaves a rectangle stuck to the cursor.
      if (event.button !== 0) return
      origin.current = toData(event)
      setDragging(normalizeRange(origin.current, origin.current))
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    [toData],
  )

  const onPointerMove = useCallback(
    (event: ReactPointerEvent<SVGElement>) => {
      if (!origin.current) return
      setDragging(normalizeRange(origin.current, toData(event)))
    },
    [toData],
  )

  const onPointerUp = useCallback(
    (event: ReactPointerEvent<SVGElement>) => {
      if (!origin.current) return
      const next = normalizeRange(origin.current, toData(event))
      origin.current = null
      setDragging(null)
      // A click with no drag clears rather than selecting nothing; see
      // `isEmptyRange`.
      const resolved = isEmptyRange(next) ? null : next
      setBrush(resolved)
      onChange?.(resolved)
    },
    [toData, onChange],
  )

  const clear = useCallback(() => {
    setBrush(null)
    setDragging(null)
    origin.current = null
    onChange?.(null)
  }, [onChange])

  return { brush, dragging, onPointerDown, onPointerMove, onPointerUp, clear }
}

/**
 * The keyboard route to the same range.
 *
 * Four number inputs, which are natively focusable, labelled, and adjustable
 * with the arrow keys -- no custom key handling to get wrong, and no ARIA
 * needed to explain a control the platform already describes.
 */
export function BrushControls({
  brush,
  bounds,
  onChange,
  xLabel,
  yLabel,
  xStep = 0.01,
  yStep = 0.01,
}: {
  brush: BrushRange | null
  bounds: BrushRange
  onChange: (brush: BrushRange | null) => void
  xLabel: string
  yLabel: string
  xStep?: number
  yStep?: number
}) {
  const current = brush ?? bounds
  const set = (patch: Partial<BrushRange>) => onChange({ ...current, ...patch })
  return (
    <fieldset className="brush-controls">
      <legend>Range</legend>
      <label>
        <span>Min {xLabel}</span>
        <input
          type="number"
          step={xStep}
          value={current.x0}
          onChange={(e) => set({ x0: Number(e.target.value) })}
        />
      </label>
      <label>
        <span>Max {xLabel}</span>
        <input
          type="number"
          step={xStep}
          value={current.x1}
          onChange={(e) => set({ x1: Number(e.target.value) })}
        />
      </label>
      <label>
        <span>Min {yLabel}</span>
        <input
          type="number"
          step={yStep}
          value={current.y0}
          onChange={(e) => set({ y0: Number(e.target.value) })}
        />
      </label>
      <label>
        <span>Max {yLabel}</span>
        <input
          type="number"
          step={yStep}
          value={current.y1}
          onChange={(e) => set({ y1: Number(e.target.value) })}
        />
      </label>
      <button type="button" className="btn ghost" onClick={() => onChange(null)}>
        Clear range
      </button>
    </fieldset>
  )
}

/**
 * The rectangle itself. Decorative: the counts are in the live region, and a
 * reader who cannot see this shape is not missing information.
 */
export function BrushRect({
  brush,
  scale,
}: {
  brush: BrushRange | null
  scale: BrushScale
}) {
  if (isEmptyRange(brush) || !brush) return null
  const x = scale.toPixelX(brush.x0)
  const y = scale.toPixelY(brush.y1)
  const width = scale.toPixelX(brush.x1) - x
  // The y axis is inverted on screen, so the height is measured from the top
  // edge the *maximum* data value maps to.
  const height = scale.toPixelY(brush.y0) - y
  if (!(width > 0) || !(height > 0)) return null
  return (
    <rect
      className="brush-rect"
      x={x}
      y={y}
      width={width}
      height={height}
      fill="var(--accent)"
      fillOpacity="0.10"
      stroke="var(--accent)"
      strokeDasharray="4 3"
      pointerEvents="none"
      aria-hidden="true"
    />
  )
}
