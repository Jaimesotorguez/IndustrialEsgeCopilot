/**
 * components/Header.tsx
 */

import { useEffect, useState } from 'react'
import { Btn } from './ui'
import { api } from '../lib/api'

interface HeaderProps {
  activeTab: string
  onTabChange: (tab: string) => void
  pendingCommands: number
  pendingQuestions: number
  emergencyStopped: boolean
  connected: boolean
  onEmergency: () => void
}

const TABS = [
  { id: 'monitor',  label: 'Monitor' },
  { id: 'data',     label: 'Datos' },
  { id: 'model',    label: 'Modelo' },
  { id: 'history',  label: 'Historial' },
  { id: 'settings', label: 'Config' },
]

export default function Header({
  activeTab, onTabChange, pendingCommands, pendingQuestions,
  emergencyStopped, connected, onEmergency,
}: HeaderProps) {
  const [clock, setClock] = useState('')

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString('es'))
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <header className="h-12 flex items-center justify-between px-4 border-b border-border bg-bg/98 flex-shrink-0 relative z-50">
      {/* Logo */}
      <div className="flex items-center gap-2.5 font-mono text-[13px] font-semibold tracking-[3px] text-cyan">
        <div className="w-7 h-7 border border-cyan flex items-center justify-center text-xs relative">
          <span>⬡</span>
          <span className="absolute inset-[3px] border border-cyan/25 animate-spin-slow" />
        </div>
        <span className="text-text1">EDGE<span className="text-cyan">COPILOT</span></span>
      </div>

      {/* Nav */}
      <nav className="flex gap-0.5">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`
              font-mono text-[10px] tracking-[1.5px] uppercase px-3 py-1.5
              border transition-all duration-150 relative
              ${activeTab === tab.id
                ? 'text-cyan border-border2 bg-cyan/5'
                : 'text-text2 border-transparent hover:text-cyan hover:border-border'}
            `}
          >
            {tab.label}
            {tab.id === 'monitor' && pendingCommands > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center w-4 h-4 rounded-full bg-red text-[9px] text-white font-mono">
                {pendingCommands}
              </span>
            )}
            {tab.id === 'model' && pendingQuestions > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center w-4 h-4 rounded-full bg-yellow text-[9px] text-bg font-mono">
                {pendingQuestions}
              </span>
            )}
            {activeTab === tab.id && (
              <span className="absolute bottom-[-1px] left-0 right-0 h-px bg-cyan" />
            )}
          </button>
        ))}
      </nav>

      {/* Right */}
      <div className="flex items-center gap-3">
        {/* Connection status */}
        <div className="flex items-center gap-1.5 font-mono text-[9px] tracking-[2px]">
          <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-green animate-pulse-dot' : 'bg-text3'}`} />
          <span className={connected ? 'text-green' : 'text-text3'}>
            {connected ? 'EN VIVO' : 'DESCONECTADO'}
          </span>
        </div>

        {/* Clock */}
        <span className="font-mono text-[12px] text-cyan tracking-[2px] min-w-[72px]">
          {clock}
        </span>

        {/* Emergency */}
        <Btn
          variant={emergencyStopped ? 'ghost' : 'emergency'}
          onClick={onEmergency}
          className={emergencyStopped ? 'border-green text-green hover:bg-green/10' : ''}
        >
          {emergencyStopped ? '▶ Reanudar' : '⬛ Parada Total'}
        </Btn>
      </div>
    </header>
  )
}
