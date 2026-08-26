// Dependency-free, accessible SVG chart primitives.
// Every chart exposes role="img" + aria-label; axes are labeled and values
// remain readable by assistive technology.

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
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${rowLabel} heatmap. ${summary}`} style={{ width: '100%' }}>
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

