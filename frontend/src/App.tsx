/**
 * App.tsx — Raíz de la aplicación
 * Ensambla todas las páginas, gestiona estado global y WebSocket.
 */

import { useState, useEffect, useCallback } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { api } from './lib/api'
import Header from './components/Header'
import Monitor from './pages/Monitor'
import Chat from './pages/Chat'
import DataSources from './pages/DataSources'
import ProcessModel from './pages/ProcessModel'
import History from './pages/History'
import Settings from './pages/Settings'

type Tab = 'monitor' | 'data' | 'model' | 'history' | 'settings'

// URL del WebSocket: en dev usa proxy de Vite, en prod va directo al backend
const WS_URL = import.meta.env.DEV
  ? `ws://${window.location.hostname}:8000/ws`
  : `ws://${window.location.host}/ws`

export default function App() {
  const [tab, setTab] = useState<Tab>('monitor')
  const [pendingCommands, setPendingCommands] = useState(0)
  const [pendingQuestions, setPendingQuestions] = useState(0)
  const [emergencyStopped, setEmergencyStopped] = useState(false)

  const ws = useWebSocket(WS_URL)

  // Carga estado inicial
  useEffect(() => {
    api.status().then(s => {
      setEmergencyStopped(s.validator?.emergency_stopped ?? false)
      setPendingCommands(s.pending_actions ?? 0)
      setPendingQuestions(s.pending_questions ?? 0)
    }).catch(() => {})
  }, [])

  // Escucha eventos globales del WebSocket
  useEffect(() => {
    return ws.subscribe(event => {
      if (event.type === 'emergency') {
        setEmergencyStopped(event.data.active)
      }
      if (event.type === 'init') {
        setEmergencyStopped(event.data.validator?.emergency_stopped ?? false)
        setPendingCommands(event.data.pending_actions ?? 0)
        setPendingQuestions(event.data.pending_questions ?? 0)
      }
      if (event.type === 'model_updated') {
        api.processModel().then(m => {
          setPendingQuestions(m.summary.pending_questions ?? 0)
        }).catch(() => {})
      }
    })
  }, [ws])

  const handleEmergency = useCallback(async () => {
    try {
      if (emergencyStopped) {
        await api.emergencyResume()
        setEmergencyStopped(false)
      } else {
        await api.emergencyStop()
        setEmergencyStopped(true)
      }
    } catch (e) {
      console.error('Error en emergencia:', e)
    }
  }, [emergencyStopped])

  // La pantalla Monitor incluye el Chat como panel lateral
  const renderContent = () => {
    switch (tab) {
      case 'monitor':
        return (
          <div className="flex h-full overflow-hidden">
            <div className="flex-1 min-w-0 overflow-hidden">
              <Monitor
                ws={ws}
                emergencyStopped={emergencyStopped}
                onCommandsChange={setPendingCommands}
              />
            </div>
            <Chat className="w-72 flex-shrink-0" />
          </div>
        )
      case 'data':
        return <DataSources />
      case 'model':
        return <ProcessModel />
      case 'history':
        return <History />
      case 'settings':
        return <Settings />
    }
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header
        activeTab={tab}
        onTabChange={t => setTab(t as Tab)}
        pendingCommands={pendingCommands}
        pendingQuestions={pendingQuestions}
        emergencyStopped={emergencyStopped}
        connected={ws.connected}
        onEmergency={handleEmergency}
      />
      <main className="flex-1 overflow-hidden">
        {renderContent()}
      </main>
    </div>
  )
}
