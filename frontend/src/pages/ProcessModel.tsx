/**
 * pages/ProcessModel.tsx
 * Visualización del grafo de proceso aprendido + preguntas al operario.
 */

import { useState, useEffect, useRef } from 'react'
import { api, ProcessModelResponse, Question } from '../lib/api'
import { Panel, Btn, ProgressBar, Empty, Spinner } from '../components/ui'

export default function ProcessModel() {
  const [model, setModel] = useState<ProcessModelResponse | null>(null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [answering, setAnswering] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    Promise.all([
      api.processModel(),
      api.nextQuestion(),
    ]).then(([m, q]) => {
      setModel(m)
      setQuestion(q.question)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  // Dibuja el grafo en canvas
  useEffect(() => {
    if (!model || !canvasRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const W = canvas.offsetWidth
    const H = canvas.offsetHeight
    canvas.width = W
    canvas.height = H

    ctx.fillStyle = '#070a0f'
    ctx.fillRect(0, 0, W, H)

    if (model.nodes.length === 0) return

    // Layout circular
    const cx = W / 2, cy = H / 2
    const r = Math.min(W, H) * 0.35
    const nodePositions: Record<string, { x: number; y: number }> = {}
    model.nodes.forEach((n, i) => {
      const angle = (i / model.nodes.length) * Math.PI * 2 - Math.PI / 2
      nodePositions[n.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
    })

    // Aristas
    model.edges.forEach(e => {
      const src = nodePositions[e.source]
      const tgt = nodePositions[e.target]
      if (!src || !tgt) return
      const alpha = Math.floor(e.confidence * 180).toString(16).padStart(2, '0')
      ctx.strokeStyle = `#1e2d3d${alpha}`
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(src.x, src.y)
      ctx.lineTo(tgt.x, tgt.y)
      ctx.stroke()
    })

    // Nodos
    model.nodes.forEach(n => {
      const pos = nodePositions[n.id]
      if (!pos) return
      const isSelected = selectedNode === n.id
      const alpha = Math.floor(n.confidence * 200).toString(16).padStart(2, '0')
      const color = n.validated ? '#00e87a' : '#00d4ff'

      ctx.beginPath()
      ctx.arc(pos.x, pos.y, isSelected ? 22 : 18, 0, Math.PI * 2)
      ctx.fillStyle = `${color}${alpha}`
      ctx.fill()
      ctx.strokeStyle = isSelected ? color : `${color}88`
      ctx.lineWidth = isSelected ? 2 : 1
      ctx.stroke()

      ctx.fillStyle = '#c8d8e8'
      ctx.font = '9px IBM Plex Mono'
      ctx.textAlign = 'center'
      ctx.fillText(n.name.split(' ')[0].slice(0, 10), pos.x, pos.y + 32)

      ctx.fillStyle = isSelected ? color : `${color}99`
      ctx.font = '8px IBM Plex Mono'
      ctx.fillText(`${(n.confidence * 100).toFixed(0)}%`, pos.x, pos.y + 4)
    })
  }, [model, selectedNode])

  const answerQuestion = async (answer: string) => {
    if (!question) return
    setAnswering(true)
    try {
      const res = await api.answerQuestion(question.id, answer)
      setQuestion(res.next_question)
      // Recarga modelo
      const m = await api.processModel()
      setModel(m)
    } catch (e) {
      console.error(e)
    } finally {
      setAnswering(false)
    }
  }

  const selectedNodeData = model?.nodes.find(n => n.id === selectedNode)

  return (
    <div className="h-full flex overflow-hidden">

      {/* LEFT: equipment list */}
      <div className="w-64 flex-shrink-0 border-r border-border flex flex-col overflow-hidden bg-s1">
        <Panel title="Equipos identificados">
          {loading ? (
            <div className="flex items-center justify-center p-8"><Spinner /></div>
          ) : (
            <div className="overflow-y-auto flex-1">
              {model?.nodes.length === 0 && <Empty text="Sin modelo aún" />}
              {model?.nodes.map(n => (
                <button
                  key={n.id}
                  onClick={() => setSelectedNode(n.id === selectedNode ? null : n.id)}
                  className={`w-full text-left p-3 border-b border-border transition-colors
                    hover:bg-s2 ${selectedNode === n.id ? 'bg-s2' : ''}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[12px] font-medium text-text1 truncate">{n.name}</span>
                    {n.validated && <span className="text-green text-[10px]">✓</span>}
                  </div>
                  <div className="font-mono text-[9px] text-text2 mb-1.5 truncate">
                    {n.tags.slice(0, 3).join(' · ')}
                    {n.tags.length > 3 && ` +${n.tags.length - 3}`}
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <ProgressBar
                        value={n.confidence * 100}
                        color={n.confidence > 0.8 ? '#00e87a' : '#00d4ff'}
                      />
                    </div>
                    <span className="font-mono text-[8px] text-text3">
                      {(n.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* CENTER: canvas */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <div className="px-3 py-2 border-b border-border bg-s1 flex items-center justify-between flex-shrink-0">
          <span className="font-mono text-[9px] tracking-[2px] text-text3 uppercase">
            Grafo de proceso
          </span>
          {model && (
            <span className="font-mono text-[9px] text-text2">
              {model.nodes.length} nodos · {model.edges.length} aristas · fase: {model.summary.learning_phase}
            </span>
          )}
        </div>

        {/* Learning status */}
        {model && (
          <div className="mx-3 mt-2 p-2.5 bg-s2 border border-border2 flex-shrink-0">
            <div className="font-mono text-[9px] tracking-[2px] text-cyan uppercase mb-1">
              {model.summary.learning_phase === 'operating' ? 'FASE 3 — OPERACIÓN' : 'FASE 2 — APRENDIZAJE'}
            </div>
            <div className="text-[11px] text-text1 mb-2">
              Modelo de proceso construido. Confianza media:{' '}
              <span className="text-cyan font-mono">{(model.summary.avg_node_confidence * 100).toFixed(0)}%</span>
            </div>
            <ProgressBar value={model.summary.avg_node_confidence * 100} />
          </div>
        )}

        {/* Canvas */}
        <div className="flex-1 relative min-h-0 mt-2">
          {loading ? (
            <div className="flex items-center justify-center h-full"><Spinner /></div>
          ) : model?.nodes.length === 0 ? (
            <Empty text="Esperando datos para aprender el modelo..." />
          ) : (
            <canvas
              ref={canvasRef}
              className="w-full h-full cursor-pointer"
              onClick={e => {
                // Detección de click en nodo
                if (!model || !canvasRef.current) return
                const rect = canvasRef.current.getBoundingClientRect()
                const mx = e.clientX - rect.left
                const my = e.clientY - rect.top
                const W = canvasRef.current.offsetWidth
                const H = canvasRef.current.offsetHeight
                const cx = W / 2, cy = H / 2
                const r = Math.min(W, H) * 0.35
                let found: string | null = null
                model.nodes.forEach((n, i) => {
                  const angle = (i / model.nodes.length) * Math.PI * 2 - Math.PI / 2
                  const nx = cx + r * Math.cos(angle)
                  const ny = cy + r * Math.sin(angle)
                  if (Math.hypot(mx - nx, my - ny) < 22) found = n.id
                })
                setSelectedNode(found)
              }}
            />
          )}
        </div>
      </div>

      {/* RIGHT: question + node detail */}
      <div className="w-72 flex-shrink-0 border-l border-border flex flex-col overflow-hidden bg-s1">
        {/* Pregunta pendiente */}
        {question && (
          <div className="p-3 border-b border-border flex-shrink-0">
            <div className="font-mono text-[9px] tracking-[2px] text-yellow uppercase mb-2">
              ❓ PREGUNTA PENDIENTE
            </div>
            <div className="text-[11px] text-text1 leading-relaxed mb-3">{question.question}</div>
            <div className="space-y-1.5">
              {question.options.map(opt => (
                <button
                  key={opt}
                  onClick={() => answerQuestion(opt)}
                  disabled={answering}
                  className="w-full text-left px-2.5 py-2 bg-s2 border border-border2
                    text-[11px] text-text1 hover:border-cyan hover:text-cyan
                    transition-colors disabled:opacity-50"
                >
                  {opt}
                </button>
              ))}
            </div>
            {answering && (
              <div className="flex items-center gap-2 mt-2">
                <Spinner />
                <span className="font-mono text-[9px] text-text3">Actualizando modelo...</span>
              </div>
            )}
          </div>
        )}

        {!question && (
          <div className="p-3 border-b border-border flex-shrink-0">
            <div className="font-mono text-[9px] tracking-[2px] text-green uppercase mb-1">
              ✓ SIN PREGUNTAS PENDIENTES
            </div>
            <div className="text-[11px] text-text2">El modelo está validado con la información disponible.</div>
          </div>
        )}

        {/* Detalle nodo */}
        <Panel title="Detalle nodo" className="flex-1 min-h-0">
          <div className="overflow-y-auto flex-1 p-3">
            {!selectedNodeData ? (
              <Empty text="Selecciona un nodo" />
            ) : (
              <div className="space-y-4">
                <div>
                  <div className="font-mono text-[8px] tracking-[2px] text-text3 uppercase mb-2">Equipo</div>
                  <div className="text-[13px] font-medium text-cyan">{selectedNodeData.name}</div>
                  <div className="flex items-center gap-2 mt-1">
                    <ProgressBar
                      value={selectedNodeData.confidence * 100}
                      color={selectedNodeData.confidence > 0.8 ? '#00e87a' : '#00d4ff'}
                    />
                    <span className="font-mono text-[9px] text-text2 flex-shrink-0">
                      {(selectedNodeData.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  {selectedNodeData.validated && (
                    <div className="font-mono text-[9px] text-green mt-1">✓ Validado por operario</div>
                  )}
                </div>
                <div>
                  <div className="font-mono text-[8px] tracking-[2px] text-text3 uppercase mb-2">Variables</div>
                  <div className="space-y-1">
                    {selectedNodeData.tags.map(tag => (
                      <div key={tag} className="flex justify-between text-[11px]">
                        <span className="font-mono text-cyan">{tag}</span>
                        <span className="text-text3">correlación fuerte</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="font-mono text-[8px] tracking-[2px] text-text3 uppercase mb-2">Relaciones</div>
                  {model?.edges
                    .filter(e => e.source === selectedNodeData.id || e.target === selectedNodeData.id)
                    .slice(0, 5)
                    .map(e => {
                      const other = e.source === selectedNodeData.id ? e.target : e.source
                      const otherNode = model.nodes.find(n => n.id === other)
                      return (
                        <div key={e.id} className="text-[10px] text-text2 py-0.5 border-b border-border">
                          {e.relation} → {otherNode?.name ?? other} ({(e.confidence * 100).toFixed(0)}%)
                        </div>
                      )
                    })}
                </div>
              </div>
            )}
          </div>
        </Panel>
      </div>
    </div>
  )
}
