import { useCallback, useEffect, useReducer, useRef } from 'react'
import { initialState, reducer } from './state'
import type { ClientMessage, ServerMessage } from './types'

const MAX_BACKOFF_MS = 15_000

function socketUrl(): string {
  const configured = import.meta.env.VITE_WS_URL as string | undefined
  if (configured) return configured
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws`
}

/** Owns the WebSocket: connects, reconnects with backoff, and re-subscribes. */
export function useWikiPulse() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const wsRef = useRef<WebSocket | null>(null)
  const wikiRef = useRef<string | null>(null) // survives reconnects

  useEffect(() => {
    let backoff = 1000
    let timer: number | undefined
    let disposed = false

    const connect = () => {
      dispatch({ kind: 'status', status: 'connecting' })
      const ws = new WebSocket(socketUrl())
      wsRef.current = ws

      ws.onopen = () => {
        backoff = 1000
        dispatch({ kind: 'status', status: 'open' })
        if (wikiRef.current) send(ws, { type: 'subscribe', wiki: wikiRef.current })
      }
      ws.onmessage = (event) => {
        try {
          dispatch({ kind: 'message', message: JSON.parse(event.data) as ServerMessage })
        } catch {
          // A malformed frame shouldn't take the dashboard down.
        }
      }
      ws.onclose = () => {
        if (disposed) return
        dispatch({ kind: 'status', status: 'closed' })
        timer = window.setTimeout(connect, backoff * (0.5 + Math.random()))
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      window.clearTimeout(timer)
      wsRef.current?.close()
    }
  }, [])

  const selectWiki = useCallback((wiki: string | null) => {
    wikiRef.current = wiki
    dispatch({ kind: 'select-wiki', wiki })
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) send(ws, { type: 'subscribe', wiki })
  }, [])

  return { state, selectWiki }
}

function send(ws: WebSocket, message: ClientMessage) {
  ws.send(JSON.stringify(message))
}
