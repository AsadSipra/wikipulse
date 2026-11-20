import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { initialState, reducer } from './state'
import type { ClientMessage, ServerMessage } from './types'

const MAX_BACKOFF_MS = 15_000

function socketUrl(): string {
  const configured = import.meta.env.VITE_WS_URL as string | undefined
  if (configured) return configured
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws`
}

/** Closing mid-handshake causes EPIPE errors in the dev proxy, so wait until it opens. */
function closeSocket(ws: WebSocket) {
  if (ws.readyState === WebSocket.CONNECTING) {
    ws.addEventListener('open', () => ws.close(), { once: true })
  } else {
    ws.close()
  }
}

/** WebSocket lifecycle: connects only while the demo runs, reconnects with backoff. */
export function useWikiPulse() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const [running, setRunning] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const wikiRef = useRef<string | null>(null) // survives reconnects

  useEffect(() => {
    if (!running) {
      dispatch({ kind: 'status', status: 'stopped' })
      return
    }
    let backoff = 1000
    let reconnectTimer: number | undefined
    let disposed = false

    const connect = () => {
      dispatch({ kind: 'status', status: 'connecting' })
      const ws = new WebSocket(socketUrl())
      wsRef.current = ws
      // Ignore stale sockets (StrictMode double mount, or closed on purpose).
      const current = () => !disposed && wsRef.current === ws

      ws.onopen = () => {
        if (!current()) return
        backoff = 1000
        dispatch({ kind: 'status', status: 'open' })
        if (wikiRef.current) send(ws, { type: 'subscribe', wiki: wikiRef.current })
      }
      ws.onmessage = (event) => {
        if (!current()) return
        try {
          dispatch({ kind: 'message', message: JSON.parse(event.data) as ServerMessage })
        } catch {
          // Skip malformed frames.
        }
      }
      ws.onclose = () => {
        if (!current()) return
        dispatch({ kind: 'status', status: 'closed' })
        reconnectTimer = window.setTimeout(connect, backoff * (0.5 + Math.random()))
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      window.clearTimeout(reconnectTimer)
      if (wsRef.current) closeSocket(wsRef.current)
      wsRef.current = null
    }
  }, [running])

  const selectWiki = useCallback((wiki: string | null) => {
    wikiRef.current = wiki
    dispatch({ kind: 'select-wiki', wiki })
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) send(ws, { type: 'subscribe', wiki })
  }, [])

  const start = useCallback(() => setRunning(true), [])
  const stop = useCallback(() => setRunning(false), [])

  return { state, running, start, stop, selectWiki }
}

function send(ws: WebSocket, message: ClientMessage) {
  ws.send(JSON.stringify(message))
}
