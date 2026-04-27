/**
 * hooks/useWebSocket.ts
 * Hook central para la conexión WebSocket con el backend.
 * Gestiona reconexión automática y distribución de eventos.
 */

import { useEffect, useRef, useState, useCallback } from 'react'

export type WsEvent =
  | { type: 'init';           data: SystemStatus }
  | { type: 'readings';       data: Record<string, number> }
  | { type: 'anomaly';        data: AnomalyEvent }
  | { type: 'command_update'; data: { id: string; status: string } }
  | { type: 'emergency';      data: { active: boolean } }
  | { type: 'model_updated';  data: object }
  | { type: 'pong' }

export interface SystemStatus {
  plant: string
  sector: string
  started: boolean
  llm: { provider: string; model: string; available: boolean }
  observer: { cycles: number; running: boolean; total_anomalies: number }
  pending_actions: number
  pending_questions: number
  validator: { emergency_stopped: boolean }
}

export interface AnomalyEvent {
  timestamp: string
  score: number
  severity: 'low' | 'medium' | 'high' | 'critical'
  description: string
  tag_ids: string[]
}

type EventHandler = (event: WsEvent) => void

export function useWebSocket(url: string = 'ws://localhost:8000/ws') {
  const [connected, setConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const handlersRef = useRef<EventHandler[]>([])
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        console.log('[WS] Conectado')
        // Ping keepalive cada 30s
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
        ws.onclose = () => clearInterval(ping)
      }

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as WsEvent
          setLastEvent(event)
          handlersRef.current.forEach(h => h(event))
        } catch { /* ignore malformed */ }
      }

      ws.onclose = () => {
        setConnected(false)
        console.log('[WS] Desconectado — reconectando en 3s...')
        reconnectTimer.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()

    } catch (e) {
      console.error('[WS] Error:', e)
      reconnectTimer.current = setTimeout(connect, 5000)
    }
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const subscribe = useCallback((handler: EventHandler) => {
    handlersRef.current.push(handler)
    return () => {
      handlersRef.current = handlersRef.current.filter(h => h !== handler)
    }
  }, [])

  return { connected, lastEvent, subscribe }
}
