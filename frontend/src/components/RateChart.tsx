import type { RatePoint } from '../types'

// A plain SVG line is enough for one series; no chart library needed.
const W = 600
const H = 120
const PAD = 4

// Each point is the edits in one 10-second slice, scaled to a per-minute rate.
// That reacts faster than the headline number (a rolling 60-second count), so
// the two can differ slightly; the caption says so.
export function RateChart({ series }: { series: RatePoint[] }) {
  if (series.length < 2) return <div className="chart-empty">Waiting for data…</div>
  const max = Math.max(1, ...series.map((p) => p.rate))
  const x = (i: number) => PAD + (i * (W - 2 * PAD)) / (series.length - 1)
  const y = (v: number) => H - PAD - (v / max) * (H - 2 * PAD)
  const line = series.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.rate).toFixed(1)}`).join(' ')
  const area = `${line} L${x(series.length - 1)},${H - PAD} L${x(0)},${H - PAD} Z`

  const minutes = Math.round(((series.length - 1) * 10) / 60)
  return (
    <>
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
      aria-label={`Edit rate per 10-second slice over the last ${minutes} minutes, peak ${max} per minute`}>
      <path d={area} className="chart-area" />
      <path d={line} className="chart-line" />
    </svg>
    <div className="chart-axis" aria-hidden="true">
      <span>{minutes} min ago</span>
      <span>peak {max}/min</span>
      <span>now</span>
    </div>
    </>
  )
}
