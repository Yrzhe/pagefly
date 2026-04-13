import { useState, useEffect, useCallback } from 'react'
import { Calendar, Plus, Trash2, Pencil, X, Check, Lock, Clock } from 'lucide-react'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface Schedule {
  id?: string
  name: string
  cron: string
  type: string
  prompt?: string
  enabled?: boolean
  source: 'system' | 'user'
}

const TYPE_COLORS: Record<string, string> = {
  review: 'bg-blue-50 text-blue-700',
  compiler: 'bg-purple-50 text-purple-700',
  ingest: 'bg-green-50 text-green-700',
  custom: 'bg-bg-tertiary text-text-secondary',
}

const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: 'Every hour', cron: '0 * * * *' },
  { label: 'Every day at 9am', cron: '0 9 * * *' },
  { label: 'Every day at midnight', cron: '0 0 * * *' },
  { label: 'Every Monday 9am', cron: '0 9 * * 1' },
  { label: 'First of month 9am', cron: '0 9 1 * *' },
]

function describeCron(cron: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [m, h, dom, mon, dow] = parts
  if (m === '0' && h !== '*' && dom === '*' && mon === '*' && dow === '*') {
    return `Daily at ${h.padStart(2, '0')}:00`
  }
  if (m === '0' && dom === '*' && mon === '*' && dow !== '*') {
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    return `Weekly on ${days[parseInt(dow)] || dow} at ${h.padStart(2, '0')}:00`
  }
  if (m === '0' && dom !== '*' && mon === '*' && dow === '*') {
    return `Monthly on day ${dom} at ${h.padStart(2, '0')}:00`
  }
  if (m === '0' && dom === '*' && mon === '*' && dow === '*' && h === '*') {
    return 'Every hour'
  }
  return cron
}

export function SchedulesPage() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(true)
  const [editor, setEditor] = useState<Schedule | null>(null)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const fetchSchedules = useCallback(async () => {
    try {
      const { data } = await api.get('/api/schedules')
      setSchedules(data.schedules || [])
    } catch { setSchedules([]) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchSchedules() }, [fetchSchedules])

  const showMsg = (type: 'ok' | 'err', text: string) => {
    setMsg({ type, text })
    setTimeout(() => setMsg(null), 3000)
  }

  const handleSave = async (s: Schedule) => {
    if (!s.name.trim() || !s.cron.trim()) {
      showMsg('err', 'Name and cron are required')
      return
    }
    try {
      if (s.id) {
        await api.put(`/api/schedules/${s.id}`, {
          name: s.name,
          cron_expr: s.cron,
          task_type: s.type,
          prompt: s.prompt || '',
          enabled: s.enabled !== false,
        })
      } else {
        await api.post('/api/schedules', {
          name: s.name,
          cron_expr: s.cron,
          task_type: s.type || 'custom',
          prompt: s.prompt || '',
        })
      }
      setEditor(null)
      await fetchSchedules()
      showMsg('ok', s.id ? 'Schedule updated' : 'Schedule created')
    } catch (e: any) {
      showMsg('err', e.response?.data?.detail || 'Save failed')
    }
  }

  const handleToggle = async (s: Schedule) => {
    if (!s.id) return
    try {
      await api.put(`/api/schedules/${s.id}`, { enabled: !s.enabled })
      await fetchSchedules()
    } catch { /* silent */ }
  }

  const handleDelete = async (s: Schedule) => {
    if (!s.id || !confirm(`Delete schedule "${s.name}"?`)) return
    try {
      await api.delete(`/api/schedules/${s.id}`)
      await fetchSchedules()
      showMsg('ok', 'Schedule deleted')
    } catch { showMsg('err', 'Delete failed') }
  }

  const systemTasks = schedules.filter(s => s.source === 'system')
  const userTasks = schedules.filter(s => s.source === 'user')

  return (
    <div className="flex flex-col h-screen overflow-y-auto">
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <Calendar size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Schedules</h1>
          <span className="text-xs text-text-tertiary">{userTasks.length} user · {systemTasks.length} system</span>
        </div>
        <button
          onClick={() => setEditor({ name: '', cron: '0 9 * * *', type: 'custom', prompt: '', source: 'user', enabled: true })}
          className="flex items-center gap-1.5 px-4 py-2 bg-accent-primary rounded-[8px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors"
        >
          <Plus size={13} /> New Schedule
        </button>
      </header>

      {msg && (
        <div className={cn('px-6 py-2 text-xs', msg.type === 'ok' ? 'bg-success/10 text-success' : 'bg-error/10 text-error')}>
          {msg.text}
        </div>
      )}

      <div className="p-6 max-w-[1000px] w-full flex flex-col gap-6">
        {loading ? (
          <div className="text-xs text-text-tertiary">Loading...</div>
        ) : (
          <>
            {/* User schedules */}
            <section className="flex flex-col gap-3">
              <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">Your Schedules</span>
              {userTasks.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-10 text-text-tertiary">
                  <Clock size={32} className="opacity-30" />
                  <p className="text-sm">No custom schedules yet</p>
                  <p className="text-[11px]">Create one to run agents on a recurring schedule</p>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {userTasks.map((s) => (
                    <ScheduleCard
                      key={s.id}
                      schedule={s}
                      onEdit={() => setEditor({ ...s })}
                      onDelete={() => handleDelete(s)}
                      onToggle={() => handleToggle(s)}
                    />
                  ))}
                </div>
              )}
            </section>

            {/* System schedules */}
            <section className="flex flex-col gap-3">
              <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-text-tertiary flex items-center gap-1">
                <Lock size={10} /> System Schedules (read-only)
              </span>
              <div className="flex flex-col gap-2">
                {systemTasks.map((s) => (
                  <ScheduleCard key={s.name} schedule={s} />
                ))}
              </div>
            </section>
          </>
        )}
      </div>

      {editor && (
        <EditorModal
          schedule={editor}
          onClose={() => setEditor(null)}
          onSave={handleSave}
          onChange={(patch) => setEditor({ ...editor, ...patch })}
        />
      )}
    </div>
  )
}

function ScheduleCard({
  schedule,
  onEdit,
  onDelete,
  onToggle,
}: {
  schedule: Schedule
  onEdit?: () => void
  onDelete?: () => void
  onToggle?: () => void
}) {
  const isUser = schedule.source === 'user'
  const typeCls = TYPE_COLORS[schedule.type] || TYPE_COLORS.custom
  const disabled = isUser && schedule.enabled === false

  return (
    <div className={cn(
      'group flex items-start gap-4 p-4 rounded-[10px] border border-border bg-bg-secondary transition-colors',
      disabled && 'opacity-60',
      isUser && 'hover:border-accent-primary/30'
    )}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-sm font-semibold text-text-primary truncate">{schedule.name}</span>
          <span className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded', typeCls)}>
            {schedule.type}
          </span>
          {!isUser && <Lock size={10} className="text-text-tertiary" />}
        </div>
        <div className="flex items-center gap-3 text-[11px] text-text-tertiary">
          <span className="flex items-center gap-1"><Clock size={10} /> {describeCron(schedule.cron)}</span>
          <code className="font-mono bg-bg-primary px-1.5 py-0.5 rounded">{schedule.cron}</code>
        </div>
        {schedule.prompt && (
          <p className="text-[11px] text-text-secondary mt-2 line-clamp-2 leading-relaxed">{schedule.prompt}</p>
        )}
      </div>

      {isUser && (
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={onToggle}
            className={cn(
              'px-2.5 py-1 rounded-full text-[10px] font-semibold transition-colors',
              schedule.enabled ? 'bg-success/20 text-success' : 'bg-bg-tertiary text-text-tertiary'
            )}
          >
            {schedule.enabled ? 'Enabled' : 'Paused'}
          </button>
          <button onClick={onEdit} className="p-1.5 rounded hover:bg-bg-tertiary text-text-secondary opacity-0 group-hover:opacity-100 transition-opacity">
            <Pencil size={12} />
          </button>
          <button onClick={onDelete} className="p-1.5 rounded hover:bg-error/10 text-error opacity-0 group-hover:opacity-100 transition-opacity">
            <Trash2 size={12} />
          </button>
        </div>
      )}
    </div>
  )
}

function EditorModal({
  schedule,
  onClose,
  onSave,
  onChange,
}: {
  schedule: Schedule
  onClose: () => void
  onSave: (s: Schedule) => void
  onChange: (patch: Partial<Schedule>) => void
}) {
  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-bg-primary rounded-[12px] shadow-lg w-[560px] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h3 className="font-heading text-sm font-bold text-text-primary">
            {schedule.id ? 'Edit Schedule' : 'New Schedule'}
          </h3>
          <button onClick={onClose} className="p-1 hover:bg-bg-secondary rounded">
            <X size={14} className="text-text-tertiary" />
          </button>
        </div>

        <div className="p-5 flex flex-col gap-4">
          <Field label="Name">
            <input
              value={schedule.name}
              onChange={(e) => onChange({ name: e.target.value })}
              placeholder="Weekly digest"
              className="w-full px-3 py-2 text-sm border border-border rounded-[6px] bg-bg-primary text-text-primary outline-none focus:border-accent-primary"
            />
          </Field>

          <Field label="Cron expression">
            <input
              value={schedule.cron}
              onChange={(e) => onChange({ cron: e.target.value })}
              placeholder="0 9 * * *"
              className="w-full px-3 py-2 text-sm font-mono border border-border rounded-[6px] bg-bg-primary text-text-primary outline-none focus:border-accent-primary"
            />
            <p className="text-[10px] text-text-tertiary mt-1.5">
              {describeCron(schedule.cron)} · Format: minute hour day month weekday
            </p>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {CRON_PRESETS.map((p) => (
                <button
                  key={p.cron}
                  type="button"
                  onClick={() => onChange({ cron: p.cron })}
                  className="text-[10px] px-2 py-1 rounded-full bg-bg-secondary hover:bg-bg-tertiary text-text-secondary transition-colors"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Task type">
            <select
              value={schedule.type}
              onChange={(e) => onChange({ type: e.target.value })}
              className="w-full px-3 py-2 text-sm border border-border rounded-[6px] bg-bg-primary text-text-primary outline-none focus:border-accent-primary"
            >
              <option value="custom">custom</option>
              <option value="review">review</option>
              <option value="compiler">compiler</option>
              <option value="ingest">ingest</option>
            </select>
          </Field>

          <Field label="Prompt (optional)">
            <textarea
              value={schedule.prompt || ''}
              onChange={(e) => onChange({ prompt: e.target.value })}
              rows={4}
              placeholder="What should the agent do when this runs?"
              className="w-full px-3 py-2 text-sm border border-border rounded-[6px] bg-bg-primary text-text-primary outline-none focus:border-accent-primary resize-none"
            />
          </Field>

          {schedule.id && (
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={schedule.enabled !== false}
                onChange={(e) => onChange({ enabled: e.target.checked })}
              />
              Enabled
            </label>
          )}
        </div>

        <div className="flex gap-2 px-5 py-3 border-t border-border">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 border border-border rounded-[6px] text-xs text-text-secondary hover:bg-bg-secondary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(schedule)}
            className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 bg-accent-primary rounded-[6px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors"
          >
            <Check size={12} /> {schedule.id ? 'Save' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-semibold text-text-tertiary">{label}</span>
      {children}
    </div>
  )
}
