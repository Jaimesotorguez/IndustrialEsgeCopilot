/**
 * pages/History.tsx
 * Historial completo y log de auditoría.
 */

import { useState, useEffect } from 'react'
import { api, HistoryEntry } from '../lib/api'
import { Panel, Badge, Empty, Spinner } from '../components/ui'

type Filter = 'all' | 'event' | 'diagnosis' | 'action'

const TYPE_LABELS: Record<string, string> = {
  event:     'EVENTO',
  diagnosis: 'DIAGNÓST.',
  action:    'ACCIÓN',
}

const SEV_COLORS: Record<string, string> = {
  critical: 'text-red', high: 'text-red',
  medium: 'text-yellow', low: 'text-green',
  pending: 'text-yellow', approved: 'text-green',
  rejected: 'text-red', completed: 'text-cyan',
}

export default function History() {
  const [entries, setEntries] = useState<HistoryEntry[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<HistoryEntry | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.history(100).then(r => {
      setEntries(r.history)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const filtered = entries.filter(e => {
    if (filter !== 'all' && e.type !== filter) return false
    if (search && !e.content.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="h-full flex overflow-hidden">

      {/* Main table */}
      <div className="flex-1 flex flex-col overflow-hidden border-r border-border min-w-0">
        {/* Toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-s1 flex-shrink-0">
          {(['all', 'event', 'diagnosis', 'action'] as Filter[]).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`font-mono text-[9px] tracking-[1px] uppercase px-2.5 py-1 border
                transition-all ${filter === f
                  ? 'border-cyan text-cyan bg-cyan/10'
                  : 'border-border2 text-text2 hover:border-cyan hover:text-cyan'}`}
            >
              {f === 'all' ? 'Todos' : TYPE_LABELS[f] || f}
            </button>
          ))}
          <div className="mx-1 w-px h-4 bg-border" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Buscar en historial..."
            className="flex-1 bg-s2 border border-border2 text-text1 font-mono text-[10px]
              px-2.5 py-1 outline-none focus:border-cyan placeholder:text-text3"
          />
          <span className="font-mono text-[9px] text-text3 ml-1">{filtered.length} registros</span>
        </div>

        {/* Header */}
        <div className="grid grid-cols-[100px_80px_80px_1fr_110px_70px] px-3 py-1.5
          border-b border-border bg-s1 font-mono text-[8px] tracking-[2px]
          text-text3 uppercase flex-shrink-0">
          <div>Timestamp</div><div>Tipo</div><div>Severidad</div>
          <div>Descripción</div><div>Equipo</div><div>Conf.</div>
        </div>

        {/* Rows */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-32"><Spinner /></div>
          ) : filtered.length === 0 ? (
            <Empty text="Sin registros" />
          ) : filtered.map((e, i) => (
            <button
              key={i}
              onClick={() => setSelected(e)}
              className={`w-full text-left grid grid-cols-[100px_80px_80px_1fr_110px_70px]
                px-3 py-2 border-b border-border transition-colors hover:bg-s2
                ${selected === e ? 'bg-s2 border-l-2 border-l-cyan' : ''}`}
            >
              <div className="font-mono text-[9px] text-text2 truncate">
                {new Date(e.timestamp).toLocaleTimeString('es')}
              </div>
              <div>
                <Badge label={TYPE_LABELS[e.type] || e.type} variant={e.type} />
              </div>
              <div className={`font-mono text-[9px] uppercase ${SEV_COLORS[e.severity] || 'text-text2'}`}>
                {e.severity}
              </div>
              <div className="text-[11px] text-text1 truncate pr-2">{e.content}</div>
              <div className="font-mono text-[9px] text-cyan truncate">{e.machine_id || '—'}</div>
              <div className="font-mono text-[9px] text-text2">—</div>
            </button>
          ))}
        </div>
      </div>

      {/* Detail panel */}
      <div className="w-80 flex-shrink-0 flex flex-col overflow-hidden bg-s1">
        <div className="px-3 py-2 border-b border-border flex-shrink-0">
          <div className="text-[13px] font-semibold text-text1 truncate">
            {selected?.content || 'Selecciona un registro'}
          </div>
          {selected && (
            <div className="font-mono text-[9px] text-text2 mt-0.5">
              {new Date(selected.timestamp).toLocaleString('es')} · {selected.type}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          {!selected ? (
            <Empty text="Haz clic en una fila" />
          ) : (
            <div className="space-y-4">
              <div>
                <div className="font-mono text-[8px] tracking-[2px] text-text3 uppercase mb-2">
                  Información general
                </div>
                {[
                  ['Timestamp', new Date(selected.timestamp).toLocaleString('es')],
                  ['Tipo', selected.type],
                  ['Severidad', selected.severity],
                  ['Equipo', selected.machine_id || '—'],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between py-1 border-b border-border text-[11px]">
                    <span className="text-text2">{k}</span>
                    <span className={`font-mono text-[10px] ${k === 'Severidad' ? SEV_COLORS[v] || 'text-text2' : 'text-text1'}`}>
                      {v}
                    </span>
                  </div>
                ))}
              </div>
              <div>
                <div className="font-mono text-[8px] tracking-[2px] text-text3 uppercase mb-2">
                  Descripción
                </div>
                <div className="text-[11px] text-text1 leading-relaxed bg-s2 p-2 border-l-2 border-border2">
                  {selected.content}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
