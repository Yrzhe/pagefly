import { useState, useCallback, useEffect, useRef } from 'react'
import { Search, FileText, BookOpen, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface SearchResult {
  type: 'knowledge' | 'wiki'
  id: string
  title: string
  snippet: string
  category?: string
  article_type?: string
}

export function SearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [selected, setSelected] = useState<SearchResult | null>(null)
  const [content, setContent] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => { inputRef.current?.focus() }, [])

  const doSearch = useCallback(async (keyword: string) => {
    if (!keyword.trim()) { setResults([]); setTotal(0); setSearched(false); return }
    setLoading(true)
    setSearched(true)
    try {
      const { data } = await api.post('/api/search', { keyword: keyword.trim() })
      setResults(data.results || [])
      setTotal(data.total || 0)
    } catch { setResults([]); setTotal(0) }
    finally { setLoading(false) }
  }, [])

  const handleInput = (value: string) => {
    setQuery(value)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(value), 400)
  }

  const selectResult = useCallback(async (r: SearchResult) => {
    setSelected(r)
    try {
      const endpoint = r.type === 'wiki' ? `/api/wiki/${r.id}` : `/api/documents/${r.id}`
      const { data } = await api.get(endpoint)
      setContent(data.content || '')
    } catch { setContent('Failed to load content.') }
  }, [])

  const token = localStorage.getItem('pagefly_token') || ''
  const apiBase = import.meta.env.VITE_API_URL || ''
  const previewContent = selected
    ? content.replace(
        /!\[([^\]]*)\]\((?!https?:\/\/)([^)]+)\)/g,
        (_, alt, path) => {
          const ep = selected.type === 'wiki' ? 'wiki' : 'documents'
          return `![${alt}](${apiBase}/api/${ep}/${selected.id}/files/${path.replace(/^\.\//, '')}?token=${token})`
        }
      )
    : ''

  return (
    <div className="flex flex-col h-screen">
      {/* Search header */}
      <header className="flex items-center gap-4 px-6 h-14 border-b border-border flex-shrink-0">
        <Search size={16} className="text-accent-primary" />
        <div className="flex-1 flex items-center gap-2 px-4 py-2 border border-border rounded-[8px] bg-bg-primary">
          <Search size={14} className="text-text-tertiary" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => handleInput(e.target.value)}
            placeholder="Search across all documents and wiki articles..."
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none"
          />
          {query && (
            <button onClick={() => { setQuery(''); setResults([]); setSearched(false); setSelected(null) }} className="p-0.5 hover:bg-bg-secondary rounded">
              <X size={12} className="text-text-tertiary" />
            </button>
          )}
        </div>
        {searched && (
          <span className="text-xs text-text-tertiary flex-shrink-0">
            {loading ? 'Searching...' : `${total} results`}
          </span>
        )}
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Results list */}
        <aside className="w-[360px] border-r border-border flex-shrink-0 overflow-y-auto">
          {!searched ? (
            <div className="flex flex-col items-center justify-center h-full text-text-tertiary gap-2">
              <Search size={36} className="opacity-20" />
              <p className="text-sm">Type to search your knowledge base</p>
            </div>
          ) : results.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-text-tertiary gap-2">
              <p className="text-sm">No results for "{query}"</p>
            </div>
          ) : (
            <div className="p-3 flex flex-col gap-1">
              {results.map((r) => (
                <button
                  key={`${r.type}-${r.id}`}
                  onClick={() => selectResult(r)}
                  className={cn(
                    'w-full text-left px-3 py-3 rounded-[8px] transition-colors',
                    selected?.id === r.id && selected?.type === r.type ? 'bg-bg-tertiary' : 'hover:bg-bg-secondary'
                  )}
                >
                  <div className="flex items-center gap-2 mb-1">
                    {r.type === 'wiki' ? (
                      <BookOpen size={12} className="text-accent-secondary flex-shrink-0" />
                    ) : (
                      <FileText size={12} className="text-accent-primary flex-shrink-0" />
                    )}
                    <span className="text-xs font-semibold text-text-primary truncate">{r.title}</span>
                    <span className={cn(
                      'text-[9px] font-bold px-1.5 py-0.5 rounded flex-shrink-0',
                      r.type === 'wiki' ? 'text-purple-600 bg-purple-50' : 'text-amber-600 bg-amber-50'
                    )}>
                      {r.type}
                    </span>
                  </div>
                  <p className="text-[11px] text-text-tertiary line-clamp-2 leading-relaxed">{r.snippet}</p>
                </button>
              ))}
            </div>
          )}
        </aside>

        {/* Preview */}
        <div className="flex-1 overflow-y-auto">
          {selected ? (
            <div className="flex flex-col h-full">
              <div className="flex items-center gap-2 px-6 py-3 border-b border-border flex-shrink-0">
                {selected.type === 'wiki' ? (
                  <BookOpen size={13} className="text-accent-secondary" />
                ) : (
                  <FileText size={13} className="text-accent-primary" />
                )}
                <span className="text-xs font-semibold text-text-primary">{selected.title}</span>
                <span className={cn(
                  'text-[9px] font-bold px-1.5 py-0.5 rounded',
                  selected.type === 'wiki' ? 'text-purple-600 bg-purple-50' : 'text-amber-600 bg-amber-50'
                )}>
                  {selected.type}
                </span>
              </div>
              <article className="flex-1 overflow-y-auto px-8 py-6 prose-pagefly">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{previewContent}</ReactMarkdown>
              </article>
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-text-tertiary text-sm">
              {searched ? 'Select a result to preview' : ''}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
