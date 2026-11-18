import { useEffect, useState } from 'react'
import type { Pulse } from '../types'

export function PulseCard({ pulse }: { pulse: Pulse | null }) {
  const age = useSecondsSince(pulse?.generated_at)

  if (!pulse) return <p className="muted">Gathering a few minutes of activity before the first summary…</p>
  return (
    <div className="pulse">
      <p className="pulse-headline">{pulse.headline}</p>
      <p>{pulse.summary}</p>
      <p className="muted small">
        {pulse.source === 'llm' ? 'AI summary' : 'AI summary unavailable · built from the numbers'} · updated {age}s ago
      </p>
    </div>
  )
}

function useSecondsSince(ts: number | undefined): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  return ts ? Math.max(0, Math.round(now / 1000 - ts)) : 0
}
