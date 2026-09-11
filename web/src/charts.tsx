// Dependency-free, accessible SVG chart primitives.
// Every chart exposes role="img" + aria-label; axes are labeled and values
// remain readable by assistive technology.

import { BrushRect, useBrush, type BrushRange, type BrushScale } from './brush'

interface Point {
  x: number
  y: number
}

export interface Series {
  name: string
  points: Point[]
  color?: string
}

function extent(values: number[]): [number, number] {
  const min = Math.min(...values)
  const max = Math.max(...values)
  return [min === max ? min - 1 : min, min === max ? max + 1 : max]
}

const PALETTE = ['var(--accent)', 'var(--ok)', 'var(--warn)', 'var(--bad)', '#a855f7', '#14b8a6']

/** Multi-series line chart with labeled axes. */
export function LineChart({
  series,
  xLabel,
  yLabel,
  height = 220,
  yMax,
}: {
  series: Series[]
  xLabel: string
  yLabel: string
  height?: number
  yMax?: number
}) {
  const W = 560
  const H = height
  const padL = 46
  const padB = 30
  const padT = 10
  const padR = 12
  const all = series.flatMap((s) => s.points)
  if (all.length === 0) return null
  const [xmin, xmax] = extent(all.map((p) => p.x))
  const ymin = 0
  const ymax = yMax ?? Math.max(...all.map((p) => p.y)) * 1.1
  const sx = (x: number) => padL + ((x - xmin) / (xmax - xmin || 1)) * (W - padL - padR)
  const sy = (y: number) => H - padB - ((y - ymin) / (ymax - ymin || 1)) * (H - padB - padT)
  const label = `${yLabel} by ${xLabel}: ${series.map((s) => `${s.name} (${s.points.length} points)`).join(', ')}`
  return (
    <figure className="chart" style={{ margin: '.6rem 0' }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ width: '100%', maxWidth: 720 }}>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(ymax * t)} y2={sy(ymax * t)} stroke="var(--border)" strokeWidth="1" />
            <text x={padL - 6} y={sy(ymax * t) + 4} textAnchor="end" fontSize="10" fill="var(--muted)">
              {(ymax * t).toFixed(1)}
            </text>
          </g>
        ))}
        {series.map((s, i) => (
          <polyline
            key={s.name}
            fill="none"
            stroke={s.color ?? PALETTE[i % PALETTE.length]}
            strokeWidth="2"
            points={s.points.map((p) => `${sx(p.x)},${sy(p.y)}`).join(' ')}
          />
        ))}
        {series.map((s, i) =>
          s.points.map((p, j) => (
            <circle key={`${i}-${j}`} cx={sx(p.x)} cy={sy(p.y)} r="2.5" fill={s.color ?? PALETTE[i % PALETTE.length]} />
          )),
        )}
        <text x={(padL + W) / 2} y={H - 4} textAnchor="middle" fontSize="11" fill="var(--muted)">
          {xLabel}
        </text>
        <text x={12} y={padT + 8} fontSize="11" fill="var(--muted)">
          {yLabel}
        </text>
      </svg>
      <figcaption className="legend">
        {series.map((s, i) => (
          <span key={s.name}>
            <span className="swatch" style={{ background: s.color ?? PALETTE[i % PALETTE.length] }} /> {s.name}
          </span>
        ))}
      </figcaption>
    </figure>
  )
}

/** Vertical-bar histogram (e.g. latency distributions). */
export function Histogram({
  bins,
  labels,
  xLabel,
  height = 180,
}: {
  bins: number[]
  labels: string[]
  xLabel: string
  height?: number
}) {
  const W = 560
  const H = height
  const padB = 28
  const max = Math.max(...bins, 1)
  const bw = (W - 20) / bins.length
  const label = `Histogram (${xLabel}): ${labels.map((l, i) => `${l}=${bins[i]}`).join(', ')}`
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ width: '100%', maxWidth: 720 }}>
      {bins.map((v, i) => {
        const h = (v / max) * (H - padB - 16)
        return (
          <g key={i}>
            <rect x={10 + i * bw + 2} y={H - padB - h} width={bw - 4} height={Math.max(h, v > 0 ? 2 : 0)} fill="var(--accent)" rx="3" />
            <text x={10 + i * bw + bw / 2} y={H - 10} textAnchor="middle" fontSize="9.5" fill="var(--muted)">
              {labels[i]}
            </text>
            <text x={10 + i * bw + bw / 2} y={H - padB - h - 4} textAnchor="middle" fontSize="9.5" fill="var(--muted)">
              {v > 0 ? v : ''}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

/** Scatter plot (e.g. cost vs success). */
export function Scatter({
  points,
  xLabel,
  yLabel,
  height = 220,
}: {
  points: { x: number; y: number; label: string }[]
  xLabel: string
  yLabel: string
  height?: number
}) {
  const W = 560
  const H = height
  const padL = 46
  const padB = 30
  if (points.length === 0) return null
  const [xmax] = extent(points.map((p) => p.x))
  const ymax = Math.max(...points.map((p) => p.y), 1) * 1.1
  const label = `${yLabel} vs ${xLabel}: ${points.length} points`
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ width: '100%', maxWidth: 720 }}>
      {points.map((p, i) => {
        const cx = padL + (p.x / (xmax || 1)) * (W - padL - 14)
        const cy = H - padB - (p.y / (ymax || 1)) * (H - padB - 12)
        return (
          <circle key={i} cx={cx} cy={cy} r="4" fill="var(--accent)" opacity="0.85">
            <title>{p.label}</title>
          </circle>
        )
      })}
      <text x={(padL + W) / 2} y={H - 4} textAnchor="middle" fontSize="11" fill="var(--muted)">
        {xLabel}
      </text>
      <text x={8} y={18} fontSize="11" fill="var(--muted)">
        {yLabel}
      </text>
    </svg>
  )
}

/** Grid heatmap (e.g. task-domain × agent success rates). */
export function Heatmap({
  rows,
  cols,
  cells,
  rowLabel,
}: {
  rows: string[]
  cols: string[]
  /** cells[r * cols.length + c], values 0..1 */
  cells: number[]
  rowLabel: string
}) {
  const cw = Math.min(90, 520 / Math.max(cols.length, 1))
  const rh = 26
  const W = 150 + cols.length * cw + 8
  const H = 24 + rows.length * rh + 6
  const color = (v: number) =>
    v <= 0 ? 'var(--bg)' : `color-mix(in srgb, var(--ok) ${Math.round(v * 80)}%, var(--bg))`
  const summary = rows
    .map((r, ri) => `${r}: ${cols.map((c, ci) => `${c}=${cells[ri * cols.length + ci]}`).join(', ')}`)
    .join('; ')
  return (
    // width:100% on a narrow viewBox scaled the whole drawing up — with one
    // agent the 248-unit box stretched across ~630px, so 10px labels rendered
    // at ~25px. Cap the rendered width at the intrinsic size so it stays 1:1.
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`${rowLabel} heatmap. ${summary}`}
      style={{ width: '100%', maxWidth: W, height: 'auto' }}
    >
      {cols.map((c, ci) => (
        <text key={c} x={148 + ci * cw + cw / 2} y={14} textAnchor="middle" fontSize="10" fill="var(--muted)">
          {c.length > 9 ? `${c.slice(0, 8)}…` : c}
        </text>
      ))}
      {rows.map((r, ri) => (
        <g key={r}>
          <text x={144} y={24 + ri * rh + rh / 2 + 4} textAnchor="end" fontSize="10.5" fill="var(--muted)">
            {r.length > 17 ? `${r.slice(0, 16)}…` : r}
          </text>
          {cols.map((c, ci) => {
            const v = cells[ri * cols.length + ci]
            return (
              <rect key={c} x={150 + ci * cw} y={24 + ri * rh} width={cw - 4} height={rh - 4} rx="4" fill={color(v)}>
                <title>{`${r} · ${c}: ${(v * 100).toFixed(0)}%`}</title>
              </rect>
            )
          })}
        </g>
      ))}
    </svg>
  )
}

/** Small progress ring for single percentages. */
export function Ring({ value, label }: { value: number; label: string }) {
  const r = 34
  const circ = 2 * Math.PI * r
  const filled = Math.max(0, Math.min(1, value)) * circ
  return (
    <svg viewBox="0 0 90 90" role="img" aria-label={`${label}: ${(value * 100).toFixed(0)}%`} width="90" height="90">
      <circle cx="45" cy="45" r={r} fill="none" stroke="var(--border)" strokeWidth="8" />
      <circle cx="45" cy="45" r={r} fill="none" stroke="var(--ok)" strokeWidth="8"
        strokeDasharray={`${filled} ${circ - filled}`} strokeLinecap="round" transform="rotate(-90 45 45)" />
      <text x="45" y="50" textAnchor="middle" fontSize="15" fontWeight="700" fill="var(--text)">
        {(value * 100).toFixed(0)}%
      </text>
    </svg>
  )
}


/**
 * Cost against accuracy, with the frontier drawn through the points nobody beats.
 *
 * Two things this does that `Scatter` does not, and both matter more than the
 * drawing. It renders the *dominated* points differently rather than as
 * anonymous dots -- the whole question is which agents are beaten on both axes
 * at once, and a chart where every dot looks the same makes the reader
 * recompute that by eye. And it never returns `null` for an empty input: an
 * agent with no measured cost cannot be on a frontier, and a blank rectangle
 * says "nothing here" when the truth is "nobody priced this run".
 */
interface ParetoProps {
  points: { agent: string; success_rate: number; cost_per_resolved_task: number | null }[]
  frontier: string[]
  height?: number
  selected?: string | null
  onSelect?: (agent: string | null) => void
  /** Data-space range to outline. The chart *shows* it; the caller decides
      what a selection means, so nothing is silently filtered out of view. */
  brush?: BrushRange | null
  onBrush?: (brush: BrushRange | null) => void
}

/**
 * The guard, which holds no hooks.
 *
 * `ParetoPlot` calls `useBrush`, so it cannot sit behind an early return: the
 * hook count would change the first time a dataset arrived with no priced agent
 * in it. Splitting here is the fix, and it also keeps `Math.max` off an empty
 * array -- spreading nothing into it yields `-Infinity`, which `|| 1` does not
 * catch because `-Infinity` is truthy.
 */
export function ParetoChart(props: ParetoProps) {
  const priced = props.points.filter((p) => p.cost_per_resolved_task !== null)
  if (priced.length === 0) return null
  return <ParetoPlot {...props} />
}

function ParetoPlot({
  points,
  frontier,
  height = 300,
  selected,
  onSelect,
  brush,
  onBrush,
}: ParetoProps) {
  const priced = points.filter((p) => p.cost_per_resolved_task !== null)

  const W = 640
  const H = height
  const padL = 62
  const padB = 38
  const padT = 14
  const padR = 18
  const costs = priced.map((p) => p.cost_per_resolved_task as number)
  const xmax = Math.max(...costs) * 1.15 || 1
  const plotW = W - padL - padR
  const plotH = H - padB - padT
  // Accuracy is a proportion, so the y axis is 0..1 always. Auto-scaling it
  // would make a 2-point spread look like the whole range.
  const at = (p: { success_rate: number; cost_per_resolved_task: number | null }) => ({
    x: padL + ((p.cost_per_resolved_task as number) / xmax) * plotW,
    y: padT + (1 - p.success_rate) * plotH,
  })

  // Both directions, because a brush drawn in pixels has to be stored in data
  // units: a rectangle kept as screen coordinates stops meaning anything the
  // moment the container resizes, and this chart is `width: 100%`.
  const scale: BrushScale = {
    toPixelX: (cost) => padL + (cost / xmax) * plotW,
    toPixelY: (rate) => padT + (1 - rate) * plotH,
    toDataX: (px) => ((px - padL) / plotW) * xmax,
    toDataY: (py) => 1 - (py - padT) / plotH,
  }

  const onFrontier = priced
    .filter((p) => frontier.includes(p.agent))
    .sort((a, b) => (a.cost_per_resolved_task as number) - (b.cost_per_resolved_task as number))
  const path = onFrontier.map(at).map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ')

  const drag = useBrush(scale, W, H, onBrush)
  // While dragging, outline what is being drawn; otherwise what the caller
  // holds. Reading the caller's value back means a range typed into the number
  // inputs appears on the chart too, which is the point of having both.
  const outline = drag.dragging ?? brush ?? null

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      // `img` is a leaf in the accessibility tree, so the per-agent buttons
      // inside it were unreachable -- axe reports `nested-interactive`, and it
      // is right. The violation is as old as the selectable points and was
      // never seen because the published dataset has one agent, so this chart
      // renders its empty state and never draws. `group` is the role for a
      // labelled container of interactive children; a static chart with no
      // `onSelect` stays an image, which is what it is.
      role={onSelect ? 'group' : 'img'}
      aria-label={`Cost against accuracy for ${priced.length} agents; ${frontier.length} on the frontier`}
      style={{ width: '100%', maxWidth: 760 }}
      className={onBrush ? 'brush-surface' : undefined}
      onPointerDown={onBrush ? drag.onPointerDown : undefined}
      onPointerMove={onBrush ? drag.onPointerMove : undefined}
      onPointerUp={onBrush ? drag.onPointerUp : undefined}
    >
      {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
        <g key={tick}>
          <line
            x1={padL}
            x2={W - padR}
            y1={padT + (1 - tick) * plotH}
            y2={padT + (1 - tick) * plotH}
            stroke="var(--border)"
            strokeDasharray="2 4"
          />
          <text x={padL - 8} y={padT + (1 - tick) * plotH + 4} textAnchor="end" fontSize="10" fill="var(--muted)">
            {Math.round(tick * 100)}%
          </text>
        </g>
      ))}
      <BrushRect brush={outline} scale={scale} />
      {onFrontier.length > 1 && (
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeDasharray="5 3" />
      )}
      {priced.map((p) => {
        const c = at(p)
        const isFrontier = frontier.includes(p.agent)
        const isSelected = selected === p.agent
        return (
          <g
            key={p.agent}
            tabIndex={0}
            role="button"
            aria-label={`${p.agent}: ${(p.success_rate * 100).toFixed(1)}% at ${p.cost_per_resolved_task} per resolved task, ${isFrontier ? 'on the frontier' : 'dominated'}`}
            aria-pressed={isSelected}
            onClick={() => onSelect?.(isSelected ? null : p.agent)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelect?.(isSelected ? null : p.agent)
              }
            }}
            style={{ cursor: onSelect ? 'pointer' : 'default' }}
          >
            {/* Shape carries the meaning as well as colour: a frontier point is
                a filled diamond, a dominated one a hollow circle. Colour alone
                fails for a reader who cannot distinguish these two hues. */}
            {isFrontier ? (
              <rect
                x={c.x - 5}
                y={c.y - 5}
                width="10"
                height="10"
                transform={`rotate(45 ${c.x} ${c.y})`}
                fill="var(--accent)"
                stroke={isSelected ? 'var(--fg)' : 'none'}
                strokeWidth="1.5"
              />
            ) : (
              <circle
                cx={c.x}
                cy={c.y}
                r="4.5"
                fill="none"
                stroke={isSelected ? 'var(--fg)' : 'var(--muted)'}
                strokeWidth="1.5"
              />
            )}
            <text x={c.x + 9} y={c.y + 4} fontSize="10" fill="var(--muted)">
              {p.agent}
            </text>
            <title>
              {p.agent}: {(p.success_rate * 100).toFixed(1)}% at {p.cost_per_resolved_task} per
              resolved task — {isFrontier ? 'on the frontier' : 'beaten on both axes'}
            </title>
          </g>
        )
      })}
      <line x1={padL} x2={W - padR} y1={padT + plotH} y2={padT + plotH} stroke="var(--border)" />
      <line x1={padL} x2={padL} y1={padT} y2={padT + plotH} stroke="var(--border)" />
      <text x={padL + plotW / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--muted)">
        cost per resolved task (lower is better)
      </text>
      <text x={10} y={12} fontSize="11" fill="var(--muted)">
        success rate
      </text>
    </svg>
  )
}
