/**
 * lib/api.ts
 * Cliente tipado para todos los endpoints del backend.
 * Nunca llamar a fetch directamente fuera de este archivo.
 */

const BASE = '/api'

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`${res.status}: ${err}`)
  }
  return res.json()
}

// ── Status ────────────────────────────────────────────────────────────────────

export const api = {

  status: () => req<SystemStatus>('/status'),

  readings: () => req<{ readings: Record<string, ReadingValue> }>('/readings'),

  events: (limit = 20) => req<{ events: AnomalyEventFull[] }>(`/events?limit=${limit}`),

  // ── Comandos ────────────────────────────────────────────────────────────────

  commands: () => req<{ commands: Command[] }>('/commands'),

  approveCommand: (id: string) =>
    req<{ status: string; success: boolean }>(`/commands/${id}/approve`, { method: 'POST' }),

  rejectCommand: (id: string) =>
    req<{ status: string }>(`/commands/${id}/reject`, { method: 'POST' }),

  // ── Emergencia ──────────────────────────────────────────────────────────────

  emergencyStop: () => req<{ status: string }>('/emergency-stop', { method: 'POST' }),

  emergencyResume: () => req<{ status: string }>('/emergency-resume', { method: 'POST' }),

  // ── Chat ────────────────────────────────────────────────────────────────────

  chat: (message: string) =>
    req<{ response: string; ts: string }>('/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),

  // ── Modelo de proceso ───────────────────────────────────────────────────────

  processModel: () => req<ProcessModelResponse>('/process-model'),

  nextQuestion: () => req<{ question: Question | null }>('/process-model/question'),

  answerQuestion: (id: string, answer: string) =>
    req<AnswerResponse>(`/process-model/question/${id}/answer`, {
      method: 'POST',
      body: JSON.stringify({ answer }),
    }),

  // ── Historial ───────────────────────────────────────────────────────────────

  history: (limit = 50) => req<{ history: HistoryEntry[] }>(`/history?limit=${limit}`),

  memoryStats: () => req<MemoryStats>('/memory/stats'),

  // ── Config ──────────────────────────────────────────────────────────────────

  config: () => req<AppConfig>('/config'),

  safetyLimits: () => req<Record<string, SafetyLimit>>('/safety/limits'),

  safetyViolations: () => req<{ violations: Violation[] }>('/safety/violations'),
}

// ── Tipos ──────────────────────────────────────────────────────────────────────

export interface SystemStatus {
  plant: string
  sector: string
  started: boolean
  llm: { provider: string; model: string; available: boolean }
  observer: { cycles: number; running: boolean; total_anomalies: number; last_anomaly_at: string | null }
  memory: { total_events: number; total_diagnoses: number; total_actions: number }
  process_graph: { nodes: number; edges: number; learning_phase: string; pending_questions: number }
  detector: { fitted: boolean; n_features: number; total_anomalies_detected: number }
  pending_actions: number
  pending_questions: number
  validator: { emergency_stopped: boolean }
}

export interface ReadingValue {
  value: number
  ts: string
  quality: number
}

export interface AnomalyEventFull {
  timestamp: string
  tag_ids: string[]
  score: number
  severity: 'low' | 'medium' | 'high' | 'critical'
  description: string
}

export interface Command {
  id: string
  machine_id: string
  action_type: string
  reason: string
  estimated_impact: string
  estimated_saving_eur: number
  risk_level: 'low' | 'medium' | 'high'
  status: string
  timestamp: string
}

export interface ProcessModelResponse {
  nodes: ProcessNode[]
  edges: ProcessEdge[]
  summary: { nodes: number; edges: number; learning_phase: string; avg_node_confidence: number }
}

export interface ProcessNode {
  id: string
  name: string
  type: string
  tags: string[]
  confidence: number
  validated: boolean
}

export interface ProcessEdge {
  id: string
  source: string
  target: string
  relation: string
  confidence: number
  correlation: number
}

export interface Question {
  id: string
  question: string
  options: string[]
  related_tags: string[]
}

export interface AnswerResponse {
  status: string
  question_id: string
  next_question: Question | null
}

export interface HistoryEntry {
  type: string
  id: string
  timestamp: string
  content: string
  severity: string
  machine_id: string | null
}

export interface MemoryStats {
  total_events: number
  total_diagnoses: number
  total_actions: number
  total_interactions: number
  pending_actions: number
}

export interface AppConfig {
  plant: { name: string; sector: string; language: string }
  llm: { provider: string; model: string }
  observer: { interval: number; threshold: number }
  safety: { require_approval: boolean }
}

export interface SafetyLimit {
  min: number
  max: number
  max_delta: number
  unit: string
}

export interface Violation {
  timestamp: string
  action_type: string
  machine_id: string
  reason: string
}
