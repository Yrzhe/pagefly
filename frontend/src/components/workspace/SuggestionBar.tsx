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
  suggestion: PendingSuggestion
  /** Called after accept/reject succeeds so the parent can reload the doc. */
  onResolved: (action: 'accept' | 'reject') => void
}

/**
 * Shows the single pending AI suggestion as an old→new diff with Accept/Reject.
 * The in-editor inline highlight is deferred (markdown-offset → ProseMirror
 * position mapping); this bar is the correct, minimal accept/reject loop.
 */
export function SuggestionBar({ docId, suggestion, onResolved }: Props) {
  const [busy, setBusy] = useState<'accept' | 'reject' | null>(null)
  const [error, setError] = useState('')

  const resolve = async (action: 'accept' | 'reject') => {
    if (busy) return
    setBusy(action)
    setError('')
    try {
      await api.post(
        `/api/workspace/documents/${docId}/suggestions/${suggestion.id}/resolve`,
        { action, resolved_by: 'human:yrzhe' },
      )
      onResolved(action)
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      const detail = err.response?.data?.detail || 'Resolve failed'
      setError(
        err.response?.status === 409
          ? `${detail} — the text changed since the AI proposed this; reject and ask again.`
          : detail,
      )
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="border-b border-border bg-amber-50/60 px-6 py-3 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Sparkles size={13} className="text-accent-primary" />
        <span className="text-xs font-bold text-text-primary">AI suggested an edit</span>
        <span className="text-[10px] text-text-tertiary">by {suggestion.created_by}</span>
      </div>

      <div className="text-xs leading-relaxed flex flex-col gap-1">
        <div className="px-2 py-1 rounded bg-red-50 text-red-700 line-through decoration-red-400 whitespace-pre-wrap break-words">
          {suggestion.quote}
        </div>
        <div className="px-2 py-1 rounded bg-green-50 text-green-700 whitespace-pre-wrap break-words">
          {suggestion.new_content || '(deletes the text above)'}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-1.5 text-[11px] text-error">
          <AlertTriangle size={12} /> {error}
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={() => resolve('accept')}
          disabled={busy !== null}
          className="flex items-center gap-1 px-3 py-1.5 bg-green-600 rounded-[6px] text-[11px] font-semibold text-white hover:bg-green-700 transition-colors disabled:opacity-60"
        >
          {busy === 'accept' ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          Accept
        </button>
        <button
          onClick={() => resolve('reject')}
          disabled={busy !== null}
          className="flex items-center gap-1 px-3 py-1.5 border border-border rounded-[6px] text-[11px] font-medium text-text-secondary hover:bg-bg-secondary transition-colors disabled:opacity-60"
        >
          {busy === 'reject' ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
          Reject
        </button>
      </div>
    </div>
  )
}
