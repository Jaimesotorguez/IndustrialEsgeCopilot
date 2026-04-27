/**
 * components/ui.tsx
 * Primitivos de UI reutilizables en toda la app.
 */

import React from 'react'

// ── Badge de severidad ────────────────────────────────────────────────────────

const SEV_STYLES: Record<string, string> = {
  critical: 'bg-red/10 text-red border border-red/30',
  high:     'bg-red/10 text-red border border-red/20',
  medium:   'bg-yellow/10 text-yellow border border-yellow/30',
  low:      'bg-green/10 text-green border border-green/30',
  pending:  'bg-yellow/10 text-yellow border border-yellow/30',
  approved: 'bg-green/10 text-green border border-green/30',
  rejected: 'bg-red/10 text-red border border-red/20',
  completed:'bg-cyan/10 text-cyan border border-cyan/30',
}

export function Badge({ label, variant }: { label: string; variant: string }) {
  const cls = SEV_STYLES[variant.toLowerCase()] ?? 'bg-border text-text2 border border-border2'
  return (
    <span className={`font-mono text-[8px] tracking-widest uppercase px-1.5 py-0.5 ${cls}`}>
      {label}
    </span>
  )
}

// ── Panel con título ──────────────────────────────────────────────────────────

export function Panel({
  title, children, className = '', action,
}: {
  title: string
  children: React.ReactNode
  className?: string
  action?: React.ReactNode
}) {
  return (
    <div className={`bg-s1 border border-border flex flex-col ${className}`}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-border flex-shrink-0">
        <span className="font-mono text-[9px] tracking-[2px] text-text3 uppercase">{title}</span>
        {action}
      </div>
      {children}
    </div>
  )
}

// ── KPI card ──────────────────────────────────────────────────────────────────

export function KpiCard({
  label, value, sub, color = 'cyan',
}: {
  label: string; value: string | number; sub?: string; color?: string
}) {
  const colorMap: Record<string, string> = {
    cyan: 'text-cyan', green: 'text-green', yellow: 'text-yellow', red: 'text-red',
  }
  return (
    <div className="bg-s1 p-2.5 flex flex-col">
      <div className="font-mono text-[8px] tracking-[2px] text-text3 uppercase mb-1">{label}</div>
      <div className={`font-mono text-xl font-semibold leading-none ${colorMap[color] ?? 'text-cyan'}`}>
        {value}
      </div>
      {sub && <div className="font-mono text-[9px] text-text2 mt-1">{sub}</div>}
    </div>
  )
}

// ── Barra de progreso ─────────────────────────────────────────────────────────

export function ProgressBar({ value, color = '#00d4ff' }: { value: number; color?: string }) {
  return (
    <div className="h-[3px] bg-border w-full">
      <div
        className="h-full transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%`, background: color }}
      />
    </div>
  )
}

// ── Dot de estado ─────────────────────────────────────────────────────────────

export function StatusDot({ status }: { status: 'ok' | 'warning' | 'critical' | 'offline' }) {
  const styles: Record<string, string> = {
    ok:       'bg-green shadow-[0_0_6px_#00e87a]',
    warning:  'bg-yellow',
    critical: 'bg-red shadow-[0_0_6px_#ff3b5c] animate-pulse-dot',
    offline:  'bg-text3',
  }
  return <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${styles[status]}`} />
}

// ── Botón ─────────────────────────────────────────────────────────────────────

export function Btn({
  children, onClick, variant = 'ghost', disabled = false, className = '',
}: {
  children: React.ReactNode
  onClick?: () => void
  variant?: 'primary' | 'ghost' | 'danger' | 'emergency'
  disabled?: boolean
  className?: string
}) {
  const base = 'font-mono text-[9px] tracking-[1.5px] uppercase px-3 py-1.5 border cursor-pointer transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed'
  const variants: Record<string, string> = {
    primary:   'bg-cyan border-cyan text-bg font-semibold hover:bg-[#00b8e0]',
    ghost:     'bg-transparent border-border2 text-text2 hover:border-cyan hover:text-cyan',
    danger:    'bg-transparent border-red text-red hover:bg-red/10',
    emergency: 'bg-red border-red text-white font-bold hover:shadow-[0_0_16px_rgba(255,59,92,0.5)]',
  }
  return (
    <button
      className={`${base} ${variants[variant]} ${className}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  )
}

// ── Spinner ───────────────────────────────────────────────────────────────────

export function Spinner() {
  return (
    <div className="w-4 h-4 border border-cyan border-t-transparent rounded-full animate-spin" />
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

export function Empty({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center h-full text-text3 font-mono text-[10px] tracking-widest uppercase">
      {text}
    </div>
  )
}
