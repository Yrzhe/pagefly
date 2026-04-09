import { useState, useEffect, useCallback } from 'react'
import { ChevronRight, ChevronDown, FileText, Search, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '@/api/client'
import { cn } from '@/lib/utils'
import { DocumentPreview } from '@/components/knowledge/DocumentPreview'
import { MetadataPanel } from '@/components/knowledge/MetadataPanel'

interface Document {
  id: string
  title: string
  description: string
  category: string
  subcategory: string
  status: string
  tags: string
  source_type: string
  relevance_score: number
  temporal_type: string
  ingested_at: string
  classified_at: string
  current_path: string
  original_filename: string
}

interface TreeNode {
  category: string
  subcategories: {
    name: string
    docs: Document[]
  }[]
  count: number
}

function buildTree(docs: Document[]): TreeNode[] {
  const map = new Map<string, Map<string, Document[]>>()
  for (const doc of docs) {
    const cat = doc.category || 'Uncategorized'
    const sub = doc.subcategory || 'General'
    if (!map.has(cat)) map.set(cat, new Map())
    const subs = map.get(cat)!
    if (!subs.has(sub)) subs.set(sub, [])
    subs.get(sub)!.push(doc)
  }
  return Array.from(map.entries()).map(([category, subs]) => ({
    category,
    subcategories: Array.from(subs.entries()).map(([name, docs]) => ({ name, docs })),
    count: Array.from(subs.values()).reduce((n, d) => n + d.length, 0),
  }))
}

export function KnowledgePage() {
  const navigate = useNavigate()
  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null)
  const [docContent, setDocContent] = useState('')
  const [filter, setFilter] = useState('')
  const [searchResults, setSearchResults] = useState<Document[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set())

  const fetchDocuments = useCallback(async () => {
    try {
      const { data } = await api.get('/api/documents', { params: { limit: 200 } })
      setDocuments(data.documents || [])
    } catch {
      setDocuments([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDocuments() }, [fetchDocuments])

  // Debounced full-text search via API
  useEffect(() => {
    if (filter.length < 2) {
      setSearchResults(null)
      return
    }
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.post('/api/search', { keyword: filter })
        // Map search results to Document-like objects
        const mapped = (data.results || []).map((r: { id: string; title: string; type: string; path: string; snippet: string }) => {
          // Try to find full doc info from loaded documents
          const full = documents.find((d) => d.id === r.id)
          if (full) return full
          // Fallback: minimal doc object
          return {
            id: r.id,
            title: r.title || r.path,
            description: r.snippet || '',
            category: r.type === 'wiki' ? 'wiki' : '',
            subcategory: '',
            status: '',
            tags: '',
            source_type: r.type,
            relevance_score: 0,
            temporal_type: '',
            ingested_at: '',
            classified_at: '',
            current_path: '',
            original_filename: '',
          } as Document
        })
        setSearchResults(mapped)
      } catch {
        setSearchResults(null)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [filter, documents])

  const selectDocument = useCallback(async (doc: Document) => {
    // Wiki results: navigate to wiki page
    if (doc.source_type === 'wiki') {
      navigate(`/wiki?id=${doc.id}`)
      return
    }
    setSelectedDoc(doc)
    try {
      const { data } = await api.get(`/api/documents/${doc.id}`)
      setDocContent(data.content || '')
    } catch {
      setDocContent('Failed to load document content.')
    }
  }, [navigate])

  const toggleCategory = (cat: string) => {
    setExpandedCats((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const displayDocs = searchResults !== null ? searchResults : documents

  const tree = buildTree(displayDocs)

  // Auto-expand first category and select first doc
  useEffect(() => {
    if (tree.length > 0 && expandedCats.size === 0) {
      setExpandedCats(new Set([tree[0].category]))
      if (!selectedDoc && tree[0].subcategories[0]?.docs[0]) {
        selectDocument(tree[0].subcategories[0].docs[0])
      }
    }
  }, [tree.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Knowledge Browser</h1>
          <span className="text-xs text-text-tertiary">{documents.length} documents</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-2 border border-border rounded-[6px] w-72">
            <Search size={14} className="text-text-tertiary" />
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search notes, tags, wiki articles..."
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none"
            />
          </div>
          <label className="flex items-center gap-1.5 px-4 py-2 bg-accent-primary rounded-[8px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors cursor-pointer">
            <Upload size={13} />
            Upload
            <input
              type="file"
              className="hidden"
              accept=".pdf,.md,.txt,.docx,.png,.jpg,.jpeg,.mp3,.wav,.m4a"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                if (!file) return
                const form = new FormData()
                form.append('file', file)
                try {
                  await api.post('/api/ingest', form, { headers: { 'Content-Type': 'multipart/form-data' } })
                  fetchDocuments()
                } catch { /* silent */ }
                e.target.value = ''
              }}
            />
          </label>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Tree Panel */}
        <aside className="w-[260px] border-r border-border flex-shrink-0 flex flex-col overflow-y-auto">
          <div className="p-4 flex flex-col gap-3">
            {/* Tree */}
            {loading ? (
              <p className="text-xs text-text-tertiary py-4 text-center">Loading...</p>
            ) : tree.length === 0 ? (
              <p className="text-xs text-text-tertiary py-4 text-center">No documents found</p>
            ) : (
              <div className="flex flex-col gap-0.5">
                {tree.map((node) => (
                  <div key={node.category}>
                    <button
                      onClick={() => toggleCategory(node.category)}
                      className="flex items-center justify-between w-full px-2 py-1.5 rounded hover:bg-bg-secondary transition-colors"
                    >
                      <div className="flex items-center gap-1.5">
                        {expandedCats.has(node.category) ? (
                          <ChevronDown size={12} className="text-text-tertiary" />
                        ) : (
                          <ChevronRight size={12} className="text-text-tertiary" />
                        )}
                        <div className="w-1.5 h-1.5 rounded-full bg-accent-primary" />
                        <span className="text-xs font-semibold text-text-primary">{node.category}</span>
                      </div>
                      <span className="text-[11px] text-text-tertiary">{node.count}</span>
                    </button>

                    {expandedCats.has(node.category) && (
                      <div className="ml-3">
                        {node.subcategories.map((sub) => (
                          <div key={sub.name}>
                            <div className="px-2 py-1 ml-2">
                              <span className="text-[11px] font-medium text-text-secondary">{sub.name}</span>
                            </div>
                            {sub.docs.map((doc) => (
                              <button
                                key={doc.id}
                                onClick={() => selectDocument(doc)}
                                className={cn(
                                  'flex items-center gap-1.5 w-full px-2 py-1.5 ml-4 rounded text-left transition-colors',
                                  selectedDoc?.id === doc.id
                                    ? 'bg-bg-tertiary border-l-2 border-accent-primary text-accent-primary'
                                    : 'text-text-secondary hover:bg-bg-secondary'
                                )}
                              >
                                <FileText size={11} />
                                <span className="text-xs truncate">{doc.title || doc.original_filename}</span>
                              </button>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* Document Preview */}
        <DocumentPreview doc={selectedDoc} content={docContent} />

        {/* Metadata Panel */}
        <MetadataPanel doc={selectedDoc} onUpdate={fetchDocuments} />
      </div>
    </div>
  )
}
