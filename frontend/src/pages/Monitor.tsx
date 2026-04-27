/**
 * pages/Monitor.tsx
 * Pantalla principal: KPIs, lista de máquinas, comandos pendientes, alertas RT.
 */

import { useState, useEffect, useCallback } from 'react'
import { api, Command, AnomalyEventFull, ReadingValue } from '../lib/api'
import { useWebSocket } from '../hooks/useWebSocket'
import { Panel, KpiCard, Badge, StatusDot, Btn, Empty, ProgressBar } from '../components/ui'

interface Props {
  ws: ReturnType<typeof useWebSocket>
  emergencyStopped: boolean
  onCommandsChange: (n: number) => void
}

interface MachineState {
  id: string
  name: string
  status: 'ok' | 'warning' | 'critical'
  temp: number
  vib: number
  pres: number
  health: number
}

// Deriva estado de máquinas desde las lecturas del TEP
// En producción esto vendría de config de planta real
const MACHINE_TAGS: Record<string, { name: string; temp: string; pres: string; vib: string }> = {
  'Reactor':      { name: 'Reactor Principal',    temp: 'XMEAS_9',  pres: 'XMEAS_7',  vib: 'XMV_1' },
  'Compresor':    { name: 'Compresor A',           temp: 'XMEAS_11', pres: 'XMEAS_13', vib: 'XMV_3' },
  'Intercamb':    { name: 'Intercambiador B',      temp: 'XMEAS_18', pres: 'XMEAS_16', vib: 'XMV_9' },
  'Separador':    { name: 'Separador C',           temp: 'XMEAS_11', pres: 'XMEAS_13', vib: 'XMV_7' },
  'Stripper':     { name: 'Stripper D',            temp: 'XMEAS_18', pres: 'XMEAS_16', vib: 'XMV_8' },
  'Empaquetadora':{ name: 'Empaquetadora',         temp: 'XMEAS_21', pres: 'XMEAS_20', vib: 'XMV_10' },
}

function deriveMachines(readings: Record<string, ReadingValue>): MachineState[] {
  return Object.entries(MACHINE_TAGS).map(([id, cfg]) => {
    const temp = readings[cfg.temp]?.value ?? 50 + Math.random() * 30
    const pres = readings[cfg.pres]?.value ?? 60 + Math.random() * 30
    const vib  = readings[cfg.vib]?.value  ?? 20 + Math.random() * 40

    // Normaliza a 0-100 para health
    const normTemp = Math.min(100, Math.max(0, (temp / 130) * 100))
    const normVib  = Math.min(100, Math.max(0, (vib / 80) * 100))
    const health = Math.max(10, 100 - normTemp * 0.4 - normVib * 0.6)

    const status: MachineState['status'] =
      health < 40 ? 'critical' : health < 65 ? 'warning' : 'ok'

    return { id, name: cfg.name, status, temp, vib, pres, health }
  })
}

// ── Modal de aprobación ───────────────────────────────────────────────────────

function CommandModal({
  cmd, onApprove, onReject, onClose,
}: {
  cmd: Command
  onApprove: () => void
  onReject: () => void
  onClose: () => void
}) {
  const riskColors = { low: 'text-green', medium: 'text-yellow', high: 'text-red' }
  const riskLabels = { low: 'BAJO', medium: 'MEDIO', high: 'ALTO' }

  return (
    <div className="fixed inset-0 bg-bg/85 backdrop-blur-sm z-50 flex items-center justify-center">
      <div className="bg-s1 border border-border2 w-[440px] animate-fade-in">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-start justify-between">
          <div>
            <div className="font-mono text-[12px] text-text1 font-medium">{cmd.action_type.replace(/_/g, ' ')}</div>
            <div className="font-mono text-[8px] text-cyan tracking-[2px] mt-1">
              PROPUESTO POR MINDAGENT · {cmd.machine_id} · {new Date(cmd.timestamp).toLocaleTimeString('es')}
            </div>
          </div>
          <button onClick={onClose} className="text-text2 hover:text-text1 text-lg leading-none">✕</button>
        </div>

        {/* Body */}
        <div className="p-4 space-y-2">
          {[
            ['Máquina', cmd.machine_id],
            ['Acción', cmd.action_type],
            ['Motivo', cmd.reason],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-border py-1.5">
              <span className="font-mono text-[10px] text-text2">{k}</span>
              <span className="font-mono text-[10px] text-text1 max-w-[240px] text-right">{v}</span>
            </div>
          ))}
          <div className="flex justify-between border-b border-border py-1.5">
            <span className="font-mono text-[10px] text-text2">Impacto estimado</span>
            <span className="font-mono text-[10px] text-green max-w-[240px] text-right">{cmd.estimated_impact}</span>
          </div>
          <div className="flex justify-between border-b border-border py-1.5">
            <span className="font-mono text-[10px] text-text2">Ahorro estimado</span>
            <span className="font-mono text-[10px] text-green">€{cmd.estimated_saving_eur.toLocaleString()}</span>
          </div>
          <div className="flex justify-between py-1.5">
            <span className="font-mono text-[10px] text-text2">Nivel de riesgo</span>
            <span className={`font-mono text-[10px] font-bold ${riskColors[cmd.risk_level]}`}>
              {riskLabels[cmd.risk_level]}
            </span>
          </div>

          {/* Warning */}
          <div className={`mt-2 p-2 border-l-2 text-[10px] leading-relaxed
            ${cmd.risk_level === 'high'
              ? 'border-red bg-red/5 text-red'
              : cmd.risk_level === 'medium'
              ? 'border-yellow bg-yellow/5 text-yellow'
              : 'border-green bg-green/5 text-green'}`}>
            {cmd.risk_level === 'high'
              ? '⚠ ACCIÓN DE ALTO RIESGO. Confirmar con supervisor antes de proceder.'
              : cmd.risk_level === 'medium'
              ? 'Riesgo moderado. Verificar que no hay operarios en la zona.'
              : 'Acción de bajo riesgo. Reversible en cualquier momento.'}
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-border flex gap-2 justify-end">
          <Btn variant="danger" onClick={onReject}>✕ Rechazar</Btn>
          <Btn variant="primary" onClick={onApprove}>✓ Aprobar y ejecutar</Btn>
        </div>
      </div>
    </div>
  )
}

// ── Monitor principal ─────────────────────────────────────────────────────────

export default function Monitor({ ws, emergencyStopped, onCommandsChange }: Props) {
  const [readings, setReadings] = useState<Record<string, ReadingValue>>({})
  const [machines, setMachines] = useState<MachineState[]>([])
  const [commands, setCommands] = useState<Command[]>([])
  const [alerts, setAlerts] = useState<Array<{ ts: string; text: string; icon: string }>>([])
  const [selectedCmd, setSelectedCmd] = useState<Command | null>(null)
  const [selectedMachine, setSelectedMachine] = useState<string | null>(null)

  // Carga inicial
  useEffect(() => {
    api.readings().then(r => {
      setReadings(r.readings)
      setMachines(deriveMachines(r.readings))
    }).catch(() => {})

    api.commands().then(r => {
      setCommands(r.commands)
      onCommandsChange(r.commands.filter(c => c.status === 'pending').length)
    }).catch(() => {})
  }, [])

  // Suscripción WebSocket
  useEffect(() => {
    return ws.subscribe(event => {
      if (event.type === 'readings') {
        const flat: Record<string, ReadingValue> = {}
        Object.entries(event.data).forEach(([tag, val]) => {
          flat[tag] = { value: val as number, ts: new Date().toISOString(), quality: 1 }
        })
        setReadings(prev => ({ ...prev, ...flat }))
        setMachines(deriveMachines({ ...readings, ...flat }))
      }
      if (event.type === 'anomaly') {
        const e = event.data
        setAlerts(prev => [{
          ts: new Date().toLocaleTimeString('es'),
          text: e.description,
          icon: e.severity === 'critical' ? '🔴' : e.severity === 'high' ? '🟠' : '🟡',
        }, ...prev.slice(0, 49)])
        // Recarga comandos cuando llega anomalía
        api.commands().then(r => {
          setCommands(r.commands)
          onCommandsChange(r.commands.filter(c => c.status === 'pending').length)
        }).catch(() => {})
      }
      if (event.type === 'command_update') {
        setCommands(prev => prev.map(c =>
          c.id === event.data.id ? { ...c, status: event.data.status } : c
        ))
      }
    })
  }, [ws, readings])

  // KPIs derivados
  const crits  = machines.filter(m => m.status === 'critical').length
  const warns  = machines.filter(m => m.status === 'warning').length
  const avgH   = machines.length ? machines.reduce((s, m) => s + m.health, 0) / machines.length : 0
  const oee    = (avgH * 0.87).toFixed(1)
  const avail  = machines.length ? Math.min(100, avgH * 0.98).toFixed(1) : '—'
  const pending = commands.filter(c => c.status === 'pending')

  const handleApprove = useCallback(async () => {
    if (!selectedCmd) return
    await api.approveCommand(selectedCmd.id)
    setCommands(prev => prev.map(c => c.id === selectedCmd.id ? { ...c, status: 'approved' } : c))
    onCommandsChange(pending.length - 1)
    setSelectedCmd(null)
  }, [selectedCmd, pending.length])

  const handleReject = useCallback(async () => {
    if (!selectedCmd) return
    await api.rejectCommand(selectedCmd.id)
    setCommands(prev => prev.map(c => c.id === selectedCmd.id ? { ...c, status: 'rejected' } : c))
    onCommandsChange(pending.length - 1)
    setSelectedCmd(null)
  }, [selectedCmd, pending.length])

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── LEFT: KPIs + Máquinas ── */}
      <div className="w-64 flex-shrink-0 flex flex-col border-r border-border overflow-hidden">
        {/* KPIs */}
        <Panel title="KPIs en vivo">
          <div className="grid grid-cols-2 gap-px bg-border">
            <KpiCard label="OEE"      value={`${oee}%`}   sub="Eficiencia"    color="cyan"   />
            <KpiCard label="Prod/h"   value="847"          sub="unidades"      color="green"  />
            <KpiCard label="Alertas"  value={warns + crits} sub="activas"      color={warns + crits > 0 ? 'yellow' : 'green'} />
            <KpiCard label="MTBF"     value="142h"         sub="disponib."     color="cyan"   />
            <KpiCard label="Disponib" value={`${avail}%`}  sub="uptime"        color="green"  />
            <KpiCard label="Críticos" value={crits}        sub="máquinas"      color={crits > 0 ? 'red' : 'green'} />
          </div>
        </Panel>

        {/* Lista de máquinas */}
        <Panel title="Equipos" className="flex-1 min-h-0">
          <div className="overflow-y-auto flex-1">
            {machines.map(m => (
              <button
                key={m.id}
                onClick={() => setSelectedMachine(m.id === selectedMachine ? null : m.id)}
                className={`w-full text-left px-3 py-2.5 border-b border-border flex items-center gap-2.5
                  transition-colors hover:bg-s2
                  ${selectedMachine === m.id ? 'bg-s2 border-l-2 border-l-cyan' : ''}
                  ${m.status === 'critical' ? 'border-l-2 border-l-red' : ''}
                  ${m.status === 'warning' ? 'border-l-2 border-l-yellow' : ''}`}
              >
                <StatusDot status={m.status} />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-[9px] text-text2 tracking-wider">{m.id}</div>
                  <div className="text-[12px] text-text1 truncate">{m.name}</div>
                  <div className="font-mono text-[9px] text-text3 mt-0.5">
                    T:{m.temp.toFixed(0)}° · V:{m.vib.toFixed(0)}Hz · P:{m.pres.toFixed(0)}%
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <div className="w-10">
                    <ProgressBar
                      value={m.health}
                      color={m.health > 70 ? '#00e87a' : m.health > 45 ? '#f5c400' : '#ff3b5c'}
                    />
                  </div>
                  <span className={`font-mono text-[9px]
                    ${m.health > 70 ? 'text-green' : m.health > 45 ? 'text-yellow' : 'text-red'}`}>
                    {m.health.toFixed(0)}%
                  </span>
                </div>
              </button>
            ))}
            {machines.length === 0 && <Empty text="Sin datos" />}
          </div>
        </Panel>
      </div>

      {/* ── CENTER: Gráfica + Alertas ── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Visualización de sensores */}
        <Panel title="Sensores en tiempo real" className="flex-1 min-h-0">
          <div className="flex-1 overflow-y-auto p-3">
            {Object.entries(readings).length === 0 ? (
              <Empty text="Esperando datos..." />
            ) : (
              <div className="grid grid-cols-3 gap-px bg-border">
                {Object.entries(readings)
                  .filter(([tag]) => !selectedMachine || Object.values(MACHINE_TAGS)
                    .find(m => m.temp === tag || m.pres === tag || m.vib === tag))
                  .slice(0, 24)
                  .map(([tag, r]) => {
                    const val = r.value
                    const isHigh = val > 95
                    const isMed  = val > 75
                    return (
                      <div key={tag} className="bg-s1 p-2">
                        <div className="font-mono text-[8px] text-text3 tracking-wider truncate">{tag}</div>
                        <div className={`font-mono text-sm font-semibold mt-0.5
                          ${isHigh ? 'text-red' : isMed ? 'text-yellow' : 'text-cyan'}`}>
                          {val.toFixed(2)}
                        </div>
                        <ProgressBar
                          value={Math.min(100, (val / 130) * 100)}
                          color={isHigh ? '#ff3b5c' : isMed ? '#f5c400' : '#00d4ff'}
                        />
                      </div>
                    )
                  })}
              </div>
            )}
          </div>
        </Panel>

        {/* Alertas */}
        <Panel title="Alertas recientes" className="h-40 flex-shrink-0">
          <div className="overflow-y-auto flex-1">
            {alerts.length === 0 ? (
              <Empty text="Sin alertas" />
            ) : alerts.map((a, i) => (
              <div key={i} className="flex gap-2 px-3 py-1.5 border-b border-border items-start">
                <span className="font-mono text-[9px] text-text3 min-w-[40px] pt-px">{a.ts}</span>
                <span className="text-xs flex-shrink-0">{a.icon}</span>
                <span className="text-[11px] text-text1 leading-snug">{a.text}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {/* ── RIGHT: Comandos ── */}
      <div className="w-72 flex-shrink-0 flex flex-col border-l border-border overflow-hidden">
        <Panel
          title="Comandos IA"
          className="flex-1 min-h-0"
          action={
            pending.length > 0
              ? <span className="font-mono text-[9px] text-yellow">{pending.length} pendiente{pending.length > 1 ? 's' : ''}</span>
              : undefined
          }
        >
          <div className="overflow-y-auto flex-1">
            {commands.length === 0 ? (
              <Empty text="Sin comandos" />
            ) : commands.slice(0, 10).map(cmd => {
              const riskColor = { low: 'text-green', medium: 'text-yellow', high: 'text-red' }[cmd.risk_level]
              const isPending = cmd.status === 'pending'
              return (
                <button
                  key={cmd.id}
                  onClick={() => isPending && !emergencyStopped && setSelectedCmd(cmd)}
                  disabled={!isPending || emergencyStopped}
                  className={`w-full text-left p-2.5 border-b border-border flex items-start gap-2
                    transition-colors
                    ${isPending && !emergencyStopped ? 'hover:bg-s2 hover:border-cyan cursor-pointer' : 'opacity-50'}
                  `}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] text-text1 font-medium truncate">
                      {cmd.action_type.replace(/_/g, ' ')}
                    </div>
                    <div className="font-mono text-[9px] text-text2 mt-0.5 truncate">{cmd.machine_id}</div>
                    <div className="text-[10px] text-text2 mt-1 line-clamp-2 leading-snug">{cmd.reason}</div>
                    {cmd.estimated_saving_eur > 0 && (
                      <div className="font-mono text-[9px] text-green mt-1">
                        Ahorro est. €{cmd.estimated_saving_eur.toLocaleString()}
                      </div>
                    )}
                  </div>
                  <Badge label={cmd.status === 'pending' ? cmd.risk_level.toUpperCase() : cmd.status.toUpperCase()}
                    variant={cmd.status === 'pending' ? cmd.risk_level : cmd.status} />
                </button>
              )
            })}
          </div>
        </Panel>

        {emergencyStopped && (
          <div className="p-2 bg-red/10 border-t border-red/30 font-mono text-[9px] text-red text-center tracking-widest">
            🛑 PARADA DE EMERGENCIA ACTIVA
          </div>
        )}
      </div>

      {/* Modal */}
      {selectedCmd && (
        <CommandModal
          cmd={selectedCmd}
          onApprove={handleApprove}
          onReject={handleReject}
          onClose={() => setSelectedCmd(null)}
        />
      )}
    </div>
  )
}
