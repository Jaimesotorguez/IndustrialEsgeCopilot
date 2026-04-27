/**
 * pages/Chat.tsx  (integrado en panel derecho del Monitor)
 * Interfaz conversacional con el agente IA.
 * Se usa tanto como página standalone como como panel lateral.
 */

import { useState, useRef, useEffect } from 'react'
import { api } from '../lib/api'
import { Btn, Spinner } from '../components/ui'

interface Message {
  role: 'user' | 'agent' | 'system'
  text: string
  ts: string
}

const QUICK_QUESTIONS = [
  '¿Qué máquina fallará primero?',
  '¿Cuál es el estado general?',
  '¿Qué acción es más urgente?',
  'Explícame el último diagnóstico',
]

interface Props {
  className?: string
}

export default function Chat({ className = '' }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'agent',
      text: '🏭 Sistema activo. Monitorizando la planta en tiempo real. ¿En qué puedo ayudarte?',
      ts: new Date().toLocaleTimeString('es'),
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (text?: string) => {
    const msg = (text || input).trim()
    if (!msg || loading) return
    setInput('')

    const userMsg: Message = { role: 'user', text: msg, ts: new Date().toLocaleTimeString('es') }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await api.chat(msg)
      setMessages(prev => [...prev, {
        role: 'agent',
        text: res.response,
        ts: new Date().toLocaleTimeString('es'),
      }])
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'system',
        text: '⚠ Error de conexión con el agente. Verifica que el backend está activo.',
        ts: new Date().toLocaleTimeString('es'),
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={`flex flex-col bg-s1 border-l border-border ${className}`}>
      {/* Title */}
      <div className="px-3 py-2 border-b border-border flex-shrink-0 flex items-center justify-between">
        <span className="font-mono text-[9px] tracking-[2px] text-text3 uppercase">Agente IA</span>
        <span className="font-mono text-[8px] text-text3">MindAgent</span>
      </div>

      {/* Thinking bar */}
      <div className={`h-[2px] flex-shrink-0 transition-all ${loading ? 'animate-thinking' : ''}`} />

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2 min-h-0">
        {messages.map((m, i) => (
          <div key={i} className="flex flex-col gap-0.5 animate-fade-in">
            <div className={`font-mono text-[8px] tracking-[2px] uppercase
              ${m.role === 'user' ? 'text-cyan text-right' : 'text-text3'}`}>
              {m.role === 'user' ? 'OPERADOR' : m.role === 'agent' ? 'MINDAGENT' : 'SISTEMA'}
            </div>
            <div className={`text-[11px] leading-relaxed px-2 py-1.5 rounded-sm
              ${m.role === 'user'
                ? 'bg-cyan/10 border border-cyan/20 ml-4 text-text1'
                : m.role === 'agent'
                ? 'bg-s2 border-l-2 border-l-cyan text-text1'
                : 'text-text3 border-l border-border pl-2 font-mono text-[9px]'
              }`}>
              {m.text}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 pl-2">
            <Spinner />
            <span className="font-mono text-[9px] text-text3">Analizando...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Quick questions */}
      <div className="flex flex-wrap gap-1 px-2 pb-1 flex-shrink-0">
        {QUICK_QUESTIONS.map(q => (
          <button
            key={q}
            onClick={() => send(q)}
            disabled={loading}
            className="font-mono text-[8px] px-1.5 py-0.5 border border-border2 text-text2
              hover:border-cyan hover:text-cyan transition-colors disabled:opacity-40"
          >
            {q.length > 20 ? q.slice(0, 20) + '…' : q}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-1.5 p-2 border-t border-border flex-shrink-0">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()}
          placeholder="Pregunta al agente..."
          disabled={loading}
          className="flex-1 bg-s2 border border-border2 text-text1 font-mono text-[11px]
            px-2 py-1.5 outline-none focus:border-cyan disabled:opacity-50
            placeholder:text-text3"
        />
        <Btn variant="primary" onClick={() => send()} disabled={loading || !input.trim()}>
          ENV
        </Btn>
      </div>
    </div>
  )
}
