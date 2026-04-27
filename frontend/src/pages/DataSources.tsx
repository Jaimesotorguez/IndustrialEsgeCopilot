/**
 * pages/DataSources.tsx
 * Configuración y estado de las fuentes de datos.
 */

import { useState, useEffect } from 'react'
import { api, AppConfig } from '../lib/api'
import { Panel, Btn, Badge } from '../components/ui'

interface SourceStatus {
  name: string
  type: string
  connected: boolean
  tags: number
  last_read: string
}

export default function DataSources() {
  const [cfg, setCfg] = useState<AppConfig | null>(null)
  const [opcuaUrl, setOpcuaUrl] = useState('opc.tcp://localhost:4840')
  const [modbusHost, setModbusHost] = useState('192.168.1.100')
  const [modbusPort, setModbusPort] = useState('502')
  const [csvPath, setCsvPath] = useState('simulator/data/')
  const [sources] = useState<SourceStatus[]>([
    { name: 'Tennessee Eastman Process', type: 'CSV', connected: true, tags: 33, last_read: 'hace 2s' },
  ])

  useEffect(() => {
    api.config().then(setCfg).catch(() => {})
  }, [])

  const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className="mb-3">
      <label className="block font-mono text-[9px] tracking-[1.5px] text-text2 uppercase mb-1">{label}</label>
      {children}
    </div>
  )

  const Input = ({ value, onChange, placeholder = '' }: {
    value: string; onChange: (v: string) => void; placeholder?: string
  }) => (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full bg-s2 border border-border2 text-text1 font-mono text-[11px]
        px-2.5 py-1.5 outline-none focus:border-cyan"
    />
  )

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="max-w-5xl mx-auto grid grid-cols-2 gap-4">

        {/* OPC-UA */}
        <Panel title="OPC-UA">
          <div className="p-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-2 h-2 rounded-full bg-text3" />
              <span className="font-mono text-[9px] text-text2">Desconectado</span>
            </div>
            <Row label="URL del servidor">
              <Input value={opcuaUrl} onChange={setOpcuaUrl} placeholder="opc.tcp://192.168.1.100:4840" />
            </Row>
            <div className="grid grid-cols-2 gap-2 mb-3">
              <div>
                <label className="block font-mono text-[9px] tracking-widest text-text2 uppercase mb-1">Usuario</label>
                <Input value="" onChange={() => {}} placeholder="opcua_user" />
              </div>
              <div>
                <label className="block font-mono text-[9px] tracking-widest text-text2 uppercase mb-1">Contraseña</label>
                <input type="password" placeholder="••••••"
                  className="w-full bg-s2 border border-border2 text-text1 font-mono text-[11px] px-2.5 py-1.5 outline-none focus:border-cyan" />
              </div>
            </div>
            <Row label="Intervalo (segundos)">
              <input defaultValue="5"
                className="w-20 bg-s2 border border-border2 text-text1 font-mono text-[11px] px-2.5 py-1.5 outline-none focus:border-cyan" />
            </Row>
            <div className="flex gap-2 mt-2">
              <Btn variant="primary">Conectar</Btn>
              <Btn variant="ghost">Descubrir tags</Btn>
            </div>
          </div>
        </Panel>

        {/* Modbus */}
        <Panel title="Modbus TCP">
          <div className="p-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-2 h-2 rounded-full bg-text3" />
              <span className="font-mono text-[9px] text-text2">Desconectado</span>
            </div>
            <div className="grid grid-cols-2 gap-2 mb-3">
              <div>
                <label className="block font-mono text-[9px] tracking-widest text-text2 uppercase mb-1">Host / IP</label>
                <Input value={modbusHost} onChange={setModbusHost} placeholder="192.168.1.100" />
              </div>
              <div>
                <label className="block font-mono text-[9px] tracking-widest text-text2 uppercase mb-1">Puerto</label>
                <Input value={modbusPort} onChange={setModbusPort} />
              </div>
            </div>
            <Row label="Registros (ej: 0-49,100-149)">
              <Input value="" onChange={() => {}} placeholder="0-49" />
            </Row>
            <div className="flex gap-2 mt-2">
              <Btn variant="primary">Conectar</Btn>
              <Btn variant="ghost">Leer registros</Btn>
            </div>
          </div>
        </Panel>

        {/* CSV */}
        <Panel title="CSV / Historian">
          <div className="p-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-2 h-2 rounded-full bg-green shadow-[0_0_6px_#00e87a]" />
              <span className="font-mono text-[9px] text-green">Activo — Tennessee Eastman</span>
            </div>
            <div
              className="border-2 border-dashed border-border2 p-5 text-center cursor-pointer
                hover:border-cyan hover:bg-cyan/5 transition-all mb-3"
              onDragOver={e => e.preventDefault()}
            >
              <div className="text-2xl mb-1">📂</div>
              <div className="font-mono text-[10px] text-text2">Arrastra CSV o haz clic para buscar</div>
              <div className="font-mono text-[8px] text-text3 mt-1">Columnas: timestamp, tag_id, value</div>
            </div>
            <Row label="Ruta del directorio">
              <Input value={csvPath} onChange={setCsvPath} />
            </Row>
            {/* Progress */}
            <div className="mt-2">
              <div className="flex justify-between font-mono text-[9px] text-text2 mb-1">
                <span>TEP Dataset cargado</span>
                <span className="text-green">✓ 33 variables · 48h</span>
              </div>
              <div className="h-1 bg-border">
                <div className="h-full bg-green w-full" />
              </div>
            </div>
          </div>
        </Panel>

        {/* Fuentes activas */}
        <Panel title="Fuentes activas">
          <div className="p-4">
            <div className="space-y-2 mb-4">
              {sources.map(s => (
                <div key={s.name} className="flex items-center gap-3 p-2.5 bg-s2 border border-border">
                  <span className="text-lg">📊</span>
                  <div className="flex-1">
                    <div className="text-[12px] font-medium text-text1">{s.name}</div>
                    <div className="font-mono text-[9px] text-text2 mt-0.5">
                      {s.type} · {s.tags} variables · {s.last_read}
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <Btn variant="ghost" className="!px-2 !py-0.5 !text-[8px]">Ver datos</Btn>
                    <Btn variant="danger" className="!px-2 !py-0.5 !text-[8px]">✕</Btn>
                  </div>
                </div>
              ))}
            </div>

            {/* Resumen */}
            <div className="border-t border-border pt-3 space-y-1.5">
              {[
                ['Variables totales', '33', 'cyan'],
                ['Registros cargados', '487.200', 'text1'],
                ['Periodo histórico', '48 horas', 'text1'],
                ['Último dato', 'hace 2s', 'green'],
                ['Anomalías detectadas', '7', 'yellow'],
                ['Modelo entrenado', '✓ Isolation Forest', 'green'],
              ].map(([k, v, c]) => (
                <div key={k} className="flex justify-between text-[11px]">
                  <span className="text-text2">{k}</span>
                  <span className={`font-mono text-[10px] text-${c}`}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  )
}
