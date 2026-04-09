import { useState, useEffect, useCallback } from 'react'
import { BookOpen, Search, Link2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface WikiArticle {
  id: string
  title: string
  article_type: string
  file_path: string
  source_document_ids: string
  created_at: string
  updated_at: string
  summary: string
}

const ARTICLE_TYPES = [
  { key: 'all', label: 'All' },
  { key: 'concept', label: 'Concept' },
  { key: 'summary', label: 'Summary' },
  { key: 'connection', label: 'Connection' },
  { key: 'insight', label: 'Insight' },
  { key: 'qa', label: 'Q&A' },
  { key: 'lint', label: 'Lint' },
  { key: 'review', label: 'Review' },
] as const

const TYPE_COLORS: Record<string, string> = {
  concept: 'bg-blue-100 text-blue-700',
  summary: 'bg-bg-tertiary text-accent-secondary',
  connection: 'bg-purple-100 text-purple-700',
  insight: 'bg-green-100 text-green-700',
  qa: 'bg-orange-100 text-orange-700',
  lint: 'bg-red-100 text-red-700',
  review: 'bg-gray-100 text-gray-600',
}

function parseSourceIds(raw: string): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map(String)
  } catch { /* not JSON */ }
  return []
}

export function WikiPage() {
  const [articles, setArticles] = useState<WikiArticle[]>([])
  const [selected, setSelected] = useState<WikiArticle | null>(null)
  const [content, setContent] = useState('')
  const [filter, setFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [loading, setLoading] = useState(true)

  const fetchArticles = useCallback(async () => {
    try {
      const { data } = await api.get('/api/wiki')
      setArticles(data.articles || [])
    } catch {
      setArticles([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchArticles() }, [fetchArticles])

  const selectArticle = useCallback(async (article: WikiArticle) => {
    setSelected(article)
    try {
      const { data } = await api.get(`/api/wiki/${article.id}`)
      setContent(data.content || '')
    } catch {
      setContent('Failed to load article content.')
    }
  }, [])

  // Auto-select first article
  useEffect(() => {
    if (articles.length > 0 && !selected) {
      selectArticle(articles[0])
    }
  }, [articles.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = articles.filter((a) => {
    const matchType = typeFilter === 'all' || a.article_type === typeFilter
    const matchSearch = !filter ||
      a.title.toLowerCase().includes(filter.toLowerCase()) ||
      a.article_type.toLowerCase().includes(filter.toLowerCase())
    return matchType && matchSearch
  })

  const sourceIds = selected ? parseSourceIds(selected.source_document_ids) : []

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <BookOpen size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Wiki Browser</h1>
          <span className="text-xs text-text-tertiary">{articles.length} articles</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-2 border border-border rounded-[6px] w-64">
          <Search size={14} className="text-text-tertiary" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search articles..."
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none"
          />
        </div>
      </header>

      {/* Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: type tabs + article list */}
        <aside className="w-[260px] border-r border-border flex-shrink-0 flex flex-col overflow-y-auto">
          <div className="p-4 flex flex-col gap-3">
            {/* Type filter pills */}
            <div className="flex flex-wrap gap-1.5">
              {ARTICLE_TYPES.map(({ key, label }) => {
                const count = key === 'all'
                  ? articles.length
                  : articles.filter((a) => a.article_type === key).length
                if (key !== 'all' && count === 0) return null
                return (
                  <button
                    key={key}
                    onClick={() => setTypeFilter(key)}
                    className={cn(
                      'px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors',
                      typeFilter === key
                        ? 'bg-accent-primary text-bg-primary'
                        : 'border border-border text-text-secondary hover:bg-bg-secondary'
                    )}
                  >
                    {label} {count > 0 && <span className="opacity-60">({count})</span>}
                  </button>
                )
              })}
            </div>

            {/* Article list */}
            {loading ? (
              <p className="text-xs text-text-tertiary py-4 text-center">Loading...</p>
            ) : filtered.length === 0 ? (
              <p className="text-xs text-text-tertiary py-4 text-center">No articles found</p>
            ) : (
              <div className="flex flex-col gap-1">
                {filtered.map((article) => (
                  <button
                    key={article.id}
                    onClick={() => selectArticle(article)}
                    className={cn(
                      'flex flex-col gap-1 w-full px-3 py-2.5 rounded-[8px] text-left transition-colors',
                      selected?.id === article.id
                        ? 'bg-bg-tertiary border-l-2 border-accent-primary'
                        : 'hover:bg-bg-secondary'
                    )}
                  >
                    <span className="text-xs font-medium text-text-primary truncate">{article.title}</span>
                    <span className={cn(
                      'self-start px-1.5 py-0.5 rounded text-[9px] font-medium',
                      TYPE_COLORS[article.article_type] || 'bg-gray-100 text-gray-600'
                    )}>
                      {article.article_type}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* Center: article content */}
        <div className="flex-1 overflow-y-auto">
          {selected ? (
            <article className="px-8 py-6 prose-pagefly">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </article>
          ) : (
            <div className="flex items-center justify-center h-full text-text-tertiary text-sm">
              Select an article to read
            </div>
          )}
        </div>

        {/* Right: article info */}
        <aside className="w-[260px] flex-shrink-0 border-l border-border overflow-y-auto p-4">
          {selected ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-3">
                <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">
                  Article Info
                </span>
                <InfoRow label="Title" value={selected.title} />
                <div className="flex flex-col gap-0.5">
                  <span className="text-[11px] text-text-tertiary">Type</span>
                  <span className={cn(
                    'self-start px-2 py-0.5 rounded text-[11px] font-medium',
                    TYPE_COLORS[selected.article_type] || 'bg-gray-100 text-gray-600'
                  )}>
                    {selected.article_type}
                  </span>
                </div>
                {selected.summary && (
                  <div className="flex flex-col gap-0.5">
                    <span className="text-[11px] text-text-tertiary">Summary</span>
                    <p className="text-xs text-text-secondary leading-relaxed">{selected.summary}</p>
                  </div>
                )}
              </div>

              <div className="h-px bg-border" />

              <div className="flex flex-col gap-2.5">
                <span className="font-mono text-[10px] font-bold uppercase tracking-[1.5px] text-text-tertiary">
                  System
                </span>
                <MetaRow label="ID" value={selected.id.slice(0, 12)} mono />
                <MetaRow label="Created" value={selected.created_at?.split('T')[0] || '—'} mono />
                <MetaRow label="Updated" value={selected.updated_at?.split('T')[0] || '—'} mono />
              </div>

              {sourceIds.length > 0 && (
                <>
                  <div className="h-px bg-border" />
                  <div className="flex flex-col gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-text-tertiary flex items-center gap-1">
                      <Link2 size={10} />
                      Source Documents
                    </span>
                    {sourceIds.map((id) => (
                      <span key={id} className="text-[11px] font-mono text-info truncate">
                        {id.slice(0, 12)}...
                      </span>
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-text-tertiary text-xs">
              No article selected
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-text-tertiary">{label}</span>
      <span className="text-xs text-text-primary">{value}</span>
    </div>
  )
}

function MetaRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between">
      <span className="text-[11px] text-text-tertiary">{label}</span>
      <span className={`text-[11px] text-text-secondary ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}
