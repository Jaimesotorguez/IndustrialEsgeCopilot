/**
 * pages/Settings.tsx
 * Configuración del sistema: LLM, límites de seguridad, parámetros.
 */

import { useState, useEffect } from 'react'
import { api, AppConfig, SafetyLimit } from '../lib/api'
import { Panel, Btn, Spinner } from '../components/ui'

export default function Settings() {
  const [cfg, setCfg] = useState<AppConfig | null>(null)
  const [limits, setLimits] = useState<Record<string, SafetyLimit>>({})
  const [loading, setLoading] = useState(true)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    Promise.all([api.config(), api.safetyLimits()])
      .then(([c, l]) => { setCfg(c); setLimits(l); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const showSaved = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const Card = ({ icon, title, children }: {
    icon: string; title: string; children: React.ReactNode
  }) => (
    <div className="bg-s1 border border-border">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-border">
        <span className="text-base">{icon}</span>
        <span className="font-mono text-[10px] tracking-[2px] text-cyan uppercase">{title}</span>
      </div>
      <div className="p-4 space-y-3">{children}</div>
    </div>
  )

  const SettingRow = ({ label, desc, children }: {
    label: string; desc?: string; children: React.ReactNode
  }) => (
    <div className="grid grid-cols-[180px_1fr] items-start gap-3">
      <div>
        <div className="font-mono text-[10px] text-text2">{label}</div>
        {desc && <div className="text-[9px] text-text3 mt-0.5">{desc}</div>}
      </div>
      {children}
    </div>
  )

  const Input = ({ value, onChange, type = 'text' }: {
    value: string; onChange: (v: string) => void; type?: string
  }) => (
    <input
      type={type}
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-s2 border border-border2 text-text1 font-mono text-[11px]
        px-2.5 py-1.5 outline-none focus:border-cyan"
    />
  )

  const Select = ({ value, onChange, options }: {
    value: string; onChange: (v: string) => void
    options: { value: string; label: string }[]
  }) => (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-s2 border border-border2 text-text1 font-mono text-[11px]
        px-2.5 py-1.5 outline-none focus:border-cyan cursor-pointer"
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )

  const Toggle = ({ on, onChange, label }: {
    on: boolean; onChange: (v: boolean) => void; label: string
  }) => (
    <div className="flex items-center gap-2.5">
      <button
        onClick={() => onChange(!on)}
        className={`w-9 h-5 relative transition-colors ${on ? 'bg-cyan' : 'bg-border'}`}
      >
        <span className={`absolute top-0.5 w-4 h-4 bg-white transition-all
          ${on ? 'left-[18px]' : 'left-0.5'}`} />
      </button>
      <span className="text-[11px] text-text1">{label}</span>
    </div>
  )

  if (loading) return (
    <div className="flex items-center justify-center h-full"><Spinner /></div>
  )

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="max-w-3xl mx-auto space-y-4">

        {/* LLM */}
        <Card icon="🤖" title="Proveedor LLM">
          <SettingRow label="Proveedor" desc="Motor de razonamiento del agente">
            <Select
              value={cfg?.llm.provider || 'claude'}
              onChange={v => setCfg(c => c ? { ...c, llm: { ...c.llm, provider: v } } : c)}
              options={[
                { value: 'claude', label: 'Claude (Anthropic) — Recomendado' },
                { value: 'openai', label: 'GPT-4o (OpenAI)' },
                { value: 'gemini', label: 'Gemini 1.5 Pro (Google)' },
                { value: 'ollama', label: 'Ollama (local, gratis)' },
              ]}
            />
          </SettingRow>
          <SettingRow label="Modelo">
            <Input
              value={cfg?.llm.model || ''}
              onChange={v => setCfg(c => c ? { ...c, llm: { ...c.llm, model: v } } : c)}
            />
          </SettingRow>
          <SettingRow label="API Key" desc="Nunca se sube a git">
            <Input value="sk-ant-••••••••••••••••" onChange={() => {}} type="password" />
          </SettingRow>
          <div className="pt-1 font-mono text-[9px] text-green">
            Coste estimado: ~€18/mes · 1.240 llamadas/mes · 89.400 tokens
          </div>
        </Card>

        {/* Seguridad */}
        <Card icon="🛡️" title="Límites de seguridad">
          <div className="font-mono text-[9px] text-text3 mb-2">
            El agente NUNCA actuará fuera de estos rangos. Solo el ingeniero puede modificarlos.
          </div>
          <table className="w-full">
            <thead>
              <tr className="font-mono text-[8px] tracking-[2px] text-text3 uppercase border-b border-border">
                <th className="text-left pb-1.5">Variable</th>
                <th className="text-left pb-1.5">Mín</th>
                <th className="text-left pb-1.5">Máx</th>
                <th className="text-left pb-1.5">Unidad</th>
                <th className="text-left pb-1.5">Delta máx</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(limits).map(([key, lim]) => (
                <tr key={key} className="border-b border-border hover:bg-s2">
                  <td className="py-1.5 pr-2 text-[11px] text-text1">{key}</td>
                  <td className="py-1.5 pr-2">
                    <input defaultValue={lim.min}
                      className="w-16 bg-s2 border border-border2 text-text1 font-mono text-[10px] px-1.5 py-0.5 outline-none focus:border-cyan" />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input defaultValue={lim.max}
                      className="w-16 bg-s2 border border-border2 text-text1 font-mono text-[10px] px-1.5 py-0.5 outline-none focus:border-cyan" />
                  </td>
                  <td className="py-1.5 pr-2 font-mono text-[10px] text-text2">{lim.unit}</td>
                  <td className="py-1.5">
                    <input defaultValue={lim.max_delta}
                      className="w-16 bg-s2 border border-border2 text-text1 font-mono text-[10px] px-1.5 py-0.5 outline-none focus:border-cyan" />
                  </td>
                </tr>
              ))}
              {Object.keys(limits).length === 0 && (
                <tr><td colSpan={5} className="py-4 text-center font-mono text-[10px] text-text3">Sin límites configurados</td></tr>
              )}
            </tbody>
          </table>
          <div className="flex gap-2 pt-1">
            <Btn variant="ghost">+ Añadir límite</Btn>
            <Btn variant="primary" onClick={showSaved}>Guardar límites</Btn>
          </div>
        </Card>

        {/* Sistema */}
        <Card icon="⚙️" title="Sistema">
          <SettingRow label="Aprobación humana" desc="Siempre requerida para comandos">
            <Toggle
              on={cfg?.safety.require_approval ?? true}
              onChange={v => setCfg(c => c ? { ...c, safety: { require_approval: v } } : c)}
              label="Activado (recomendado)"
            />
          </SettingRow>
          <SettingRow label="Idioma del agente">
            <Select
              value={cfg?.plant.language || 'es'}
              onChange={v => setCfg(c => c ? { ...c, plant: { ...c.plant, language: v } } : c)}
              options={[
                { value: 'es', label: 'Español' },
                { value: 'en', label: 'English' },
                { value: 'fr', label: 'Français' },
                { value: 'de', label: 'Deutsch' },
              ]}
            />
          </SettingRow>
          <SettingRow label="Sector de la planta" desc="Ajusta contexto del agente">
            <Select
              value={cfg?.plant.sector || 'general'}
              onChange={v => setCfg(c => c ? { ...c, plant: { ...c.plant, sector: v } } : c)}
              options={[
                { value: 'alimentacion', label: 'Alimentación y bebidas' },
                { value: 'farmaceutica', label: 'Farmacéutica' },
                { value: 'automocion', label: 'Automoción' },
                { value: 'quimica', label: 'Química' },
                { value: 'general', label: 'General' },
              ]}
            />
          </SettingRow>
          <SettingRow label="Intervalo observación">
            <div className="flex items-center gap-2">
              <input
                type="number"
                defaultValue={cfg?.observer.interval || 5}
                className="w-20 bg-s2 border border-border2 text-text1 font-mono text-[11px] px-2.5 py-1.5 outline-none focus:border-cyan"
              />
              <span className="text-[11px] text-text2">segundos</span>
            </div>
          </SettingRow>
          <SettingRow label="Umbral anomalía" desc="0 = muy sensible · 1 = solo críticos">
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                defaultValue={cfg?.observer.threshold || 0.7}
                className="w-20 bg-s2 border border-border2 text-text1 font-mono text-[11px] px-2.5 py-1.5 outline-none focus:border-cyan"
              />
            </div>
          </SettingRow>
          <div className="flex gap-2 pt-1">
            <Btn variant="primary" onClick={showSaved}>
              {saved ? '✓ Guardado' : 'Guardar configuración'}
            </Btn>
            <Btn variant="ghost">Exportar config.yaml</Btn>
          </div>
        </Card>

      </div>
    </div>
  )
}
