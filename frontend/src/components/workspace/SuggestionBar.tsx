import { useState } from 'react'
import { Sparkles, Check, X, Loader2, AlertTriangle } from 'lucide-react'
import api from '@/api/client'

export interface PendingSuggestion {
  id: string
  document_id: string
  quote: string
  new_content: string | null
  created_by: string
  rejection_reason?: string | null
}

interface Props {
  docId: string
  suggestions: PendingSuggestion[]
  onResolved: (action: 'accept' | 'reject') => void
}

export function SuggestionBar({ docId, suggestions, onResolved }: Props) {
  const [busy, setBusy] = useState<Record<string, 'accept' | 'reject'>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})

  const resolve = async (suggestion: PendingSuggestion, action: 'accept' | 'reject') => {
    if (busy[suggestion.id]) return
    setBusy((prev) => ({ ...prev, [suggestion.id]: action }))
    setErrors((prev) => ({ ...prev, [suggestion.id]: '' }))
    try {
      await api.post(
        `/api/workspace/documents/${docId}/suggestions/${suggestion.id}/resolve`,
        { action, resolved_by: 'human' },
      )
      onResolved(action)
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      const detail = err.response?.data?.detail || 'Resolve failed'
      setErrors((prev) => ({
        ...prev,
        [suggestion.id]: err.response?.status === 409
          ? `${detail} — text changed since proposal; reject and ask again.`
          : detail,
      }))
    } finally {
      setBusy((prev) => { const n = { ...prev }; delete n[suggestion.id]; return n })
    }
  }

  const resolveAll = async (action: 'accept' | 'reject') => {
    for (const s of suggestions) {
      await resolve(s, action)
    }
  }

  if (suggestions.length === 0) return null

  return (
    <div className="border-b border-border bg-amber-50/60 px-6 py-3 flex flex-col gap-3 max-h-[300px] overflow-y-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles size={13} className="text-accent-primary" />
          <span className="text-xs font-bold text-text-primary">
            {suggestions.length} pending suggestion{suggestions.length > 1 ? 's' : ''}
          </span>
        </div>
        {suggestions.length > 1 && (
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => resolveAll('accept')}
              className="flex items-center gap-1 px-2 py-1 bg-green-600 rounded text-[10px] font-semibold text-white hover:bg-green-700 transition-colors"
            >
              <Check size={10} /> Accept All
            </button>
            <button
              onClick={() => resolveAll('reject')}
              className="flex items-center gap-1 px-2 py-1 border border-border rounded text-[10px] font-medium text-text-secondary hover:bg-bg-secondary transition-colors"
            >
              <X size={10} /> Reject All
            </button>
          </div>
        )}
      </div>

      {suggestions.map((suggestion) => (
        <div key={suggestion.id} className="flex flex-col gap-1.5 pb-2 border-b border-border/50 last:border-b-0 last:pb-0">
          <div className="text-xs leading-relaxed flex flex-col gap-0.5">
            <div className="px-2 py-1 rounded bg-red-50 text-red-700 line-through decoration-red-400 whitespace-pre-wrap break-words text-[11px]">
              {suggestion.quote}
            </div>
            <div className="px-2 py-1 rounded bg-green-50 text-green-700 whitespace-pre-wrap break-words text-[11px]">
              {suggestion.new_content || '(delete)'}
            </div>
          </div>

          {errors[suggestion.id] && (
            <div className="flex items-center gap-1 text-[10px] text-error">
              <AlertTriangle size={10} /> {errors[suggestion.id]}
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              onClick={() => resolve(suggestion, 'accept')}
              disabled={!!busy[suggestion.id]}
              className="flex items-center gap-1 px-2.5 py-1 bg-green-600 rounded-[5px] text-[10px] font-semibold text-white hover:bg-green-700 transition-colors disabled:opacity-60"
            >
              {busy[suggestion.id] === 'accept' ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />}
              Accept
            </button>
            <button
              onClick={() => resolve(suggestion, 'reject')}
              disabled={!!busy[suggestion.id]}
              className="flex items-center gap-1 px-2.5 py-1 border border-border rounded-[5px] text-[10px] font-medium text-text-secondary hover:bg-bg-secondary transition-colors disabled:opacity-60"
            >
              {busy[suggestion.id] === 'reject' ? <Loader2 size={10} className="animate-spin" /> : <X size={10} />}
              Reject
            </button>
            <span className="text-[9px] text-text-tertiary">by {suggestion.created_by}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
