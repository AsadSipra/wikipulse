import type { RatePoint } from '../types'

// A plain SVG line is enough for one series; no chart library needed.
const W = 600
const H = 120
const PAD = 4

export function RateChart({ series }: { series: RatePoint[] }) {
  if (series.length < 2) return <div className="chart-empty">Waiting for data…</div>
  const max = Math.max(1, ...series.map((p) => p.rate))
  const x = (i: number) => PAD + (i * (W - 2 * PAD)) / (series.length - 1)
  const y = (v: number) => H - PAD - (v / max) * (H - 2 * PAD)
  const line = series.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.rate).toFixed(1)}`).join(' ')
  const area = `${line} L${x(series.length - 1)},${H - PAD} L${x(0)},${H - PAD} Z`

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
      aria-label={`Edits per minute over the last ${series.length * 10} seconds, peak ${max}`}>
      <path d={area} className="chart-area" />
      <path d={line} className="chart-line" />
    </svg>
  )
}
