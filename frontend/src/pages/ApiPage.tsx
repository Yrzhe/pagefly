import { useState, useEffect, useCallback } from 'react'
import { Key, Copy, Trash2, Plus, Check, ExternalLink } from 'lucide-react'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface Token {
  id: string
  name: string
  token_prefix: string
  created_at: string
}

const API_DOCS = [
  { group: 'Ingest', endpoints: [
    { method: 'POST', path: '/api/ingest', desc: 'Upload file (pdf, md, docx, image, audio)' },
  ]},
  { group: 'Documents', endpoints: [
    { method: 'GET', path: '/api/documents', desc: 'List documents (query: category, status, search, limit, offset)' },
    { method: 'GET', path: '/api/documents/{id}', desc: 'Get document metadata + content' },
    { method: 'PUT', path: '/api/documents/{id}/content', desc: 'Update document content' },
    { method: 'GET', path: '/api/documents/{id}/delete-preview', desc: 'Preview deletion impact' },
    { method: 'DELETE', path: '/api/documents/{id}?confirm=true', desc: 'Delete document' },
    { method: 'GET', path: '/api/documents/{id}/files/{path}', desc: 'Serve document file (image etc)' },
  ]},
  { group: 'Wiki', endpoints: [
    { method: 'GET', path: '/api/wiki', desc: 'List wiki articles' },
    { method: 'GET', path: '/api/wiki/{id}', desc: 'Get wiki article content' },
  ]},
  { group: 'Query & Search', endpoints: [
    { method: 'POST', path: '/api/query', desc: 'Agent-powered Q&A (body: {question})' },
    { method: 'POST', path: '/api/search', desc: 'Full-text search (body: {keyword})' },
  ]},
  { group: 'Graph', endpoints: [
    { method: 'GET', path: '/api/graph', desc: 'Knowledge graph nodes + edges' },
  ]},
  { group: 'Workspace', endpoints: [
    { method: 'GET', path: '/api/workspace', desc: 'List workspace folders' },
    { method: 'POST', path: '/api/workspace', desc: 'Create folder (body: {name})' },
    { method: 'GET', path: '/api/workspace/{name}/content', desc: 'Read document.md' },
    { method: 'PUT', path: '/api/workspace/{name}/content', desc: 'Update document.md' },
    { method: 'POST', path: '/api/workspace/{name}/ingest', desc: 'Send folder to ingest pipeline' },
  ]},
  { group: 'Schedules', endpoints: [
    { method: 'GET', path: '/api/schedules', desc: 'List scheduled tasks' },
    { method: 'POST', path: '/api/schedules', desc: 'Create schedule' },
    { method: 'PUT', path: '/api/schedules/{id}', desc: 'Update schedule' },
    { method: 'DELETE', path: '/api/schedules/{id}', desc: 'Delete schedule' },
  ]},
  { group: 'Tokens', endpoints: [
    { method: 'GET', path: '/api/tokens', desc: 'List tokens (master token)' },
    { method: 'POST', path: '/api/tokens', desc: 'Create token (body: {name})' },
    { method: 'DELETE', path: '/api/tokens/{id}', desc: 'Revoke token' },
  ]},
  { group: 'System', endpoints: [
    { method: 'GET', path: '/api/stats', desc: 'System statistics' },
    { method: 'GET', path: '/health', desc: 'Health check (no auth)' },
  ]},
]

const METHOD_COLORS: Record<string, string> = {
  GET: 'text-green-700 bg-green-50',
  POST: 'text-blue-700 bg-blue-50',
  PUT: 'text-amber-700 bg-amber-50',
  DELETE: 'text-red-700 bg-red-50',
}

// Store created tokens locally so user can copy them later
function getLocalTokens(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem('pagefly_api_tokens') || '{}') } catch { return {} }
}
function saveLocalToken(id: string, token: string) {
  const stored = getLocalTokens()
  localStorage.setItem('pagefly_api_tokens', JSON.stringify({ ...stored, [id]: token }))
}
function removeLocalToken(id: string) {
  const stored = getLocalTokens()
  delete stored[id]
  localStorage.setItem('pagefly_api_tokens', JSON.stringify(stored))
}

export function ApiPage() {
  const [tokens, setTokens] = useState<Token[]>([])
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const localTokens = getLocalTokens()
  const baseUrl = import.meta.env.VITE_API_URL || window.location.origin

  const fetchTokens = useCallback(async () => {
    try {
      const { data } = await api.get('/api/tokens')
      setTokens(data.tokens || [])
    } catch { setTokens([]) }
  }, [])

  useEffect(() => { fetchTokens() }, [fetchTokens])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const { data } = await api.post('/api/tokens', { name: newName.trim() })
      saveLocalToken(data.id, data.token)
      setNewName('')
      await fetchTokens()
      copyToClipboard(data.token, data.id)
    } catch { /* silent */ }
    finally { setCreating(false) }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Revoke this token? Any integrations using it will stop working.')) return
    try {
      await api.delete(`/api/tokens/${id}`)
      removeLocalToken(id)
      await fetchTokens()
    } catch { /* silent */ }
  }

  const copyToClipboard = (text: string, id?: string) => {
    navigator.clipboard.writeText(text)
    setCopied(id || 'general')
    setTimeout(() => setCopied(null), 2000)
  }

  const buildFullDocs = () => {
    let doc = `# PageFly API\n\nBase URL: ${baseUrl}\n\n## Authentication\n\nInclude Bearer token in Authorization header:\n\`\`\`\ncurl -H "Authorization: Bearer <your-token>" ${baseUrl}/api/documents\n\`\`\`\n\n## Endpoints\n\n`
    for (const group of API_DOCS) {
      doc += `### ${group.group}\n\n`
      for (const ep of group.endpoints) {
        doc += `- \`${ep.method} ${ep.path}\` — ${ep.desc}\n`
      }
      doc += '\n'
    }
    return doc
  }

  return (
    <div className="flex flex-col h-screen">
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <Key size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">API & Tokens</h1>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Base URL:</span>
          <code className="text-xs font-mono text-accent-secondary bg-bg-tertiary px-2 py-1 rounded">{baseUrl}</code>
          <button onClick={() => copyToClipboard(baseUrl, 'base')} className="p-1.5 hover:bg-bg-secondary rounded transition-colors">
            {copied === 'base' ? <Check size={12} className="text-success" /> : <Copy size={12} className="text-text-tertiary" />}
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Tokens */}
        <aside className="w-[340px] border-r border-border flex-shrink-0 overflow-y-auto p-4 flex flex-col gap-4">
          <div className="flex flex-col gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">API Tokens</span>

            {/* Create */}
            <div className="flex gap-2">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                placeholder="Token name (e.g. My Bot)"
                className="flex-1 px-3 py-2 text-xs border border-border rounded-[6px] bg-bg-primary text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary"
              />
              <button
                onClick={handleCreate}
                disabled={creating || !newName.trim()}
                className="flex items-center gap-1 px-3 py-2 bg-accent-primary rounded-[6px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60"
              >
                <Plus size={12} /> Create
              </button>
            </div>
          </div>

          {/* Token list */}
          {tokens.length === 0 ? (
            <p className="text-xs text-text-tertiary text-center py-6">No tokens yet</p>
          ) : (
            <div className="flex flex-col gap-2">
              {tokens.map((t) => {
                const fullToken = localTokens[t.id]
                const displayToken = fullToken || `${t.token_prefix}...`
                return (
                  <div key={t.id} className="flex flex-col gap-1.5 p-3 bg-bg-secondary rounded-[8px] border border-border">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-text-primary">{t.name}</span>
                      <button onClick={() => handleDelete(t.id)} className="p-1 hover:bg-error/10 rounded text-text-tertiary hover:text-error transition-colors">
                        <Trash2 size={11} />
                      </button>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <code className="flex-1 text-[10px] font-mono text-text-secondary bg-bg-primary px-2 py-1 rounded truncate">{displayToken}</code>
                      <button
                        onClick={() => copyToClipboard(fullToken || displayToken, t.id)}
                        className="p-1.5 hover:bg-bg-tertiary rounded transition-colors flex-shrink-0"
                      >
                        {copied === t.id ? <Check size={11} className="text-success" /> : <Copy size={11} className="text-text-tertiary" />}
                      </button>
                    </div>
                    <span className="text-[9px] text-text-tertiary">
                      Created {t.created_at?.split('T')[0] || '—'}
                      {!fullToken && ' · full token only available locally'}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </aside>

        {/* Right: API Docs */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="flex items-center justify-between mb-6">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">API Documentation</span>
            <button
              onClick={() => copyToClipboard(buildFullDocs(), 'docs')}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-border rounded-[6px] text-[11px] font-semibold text-text-secondary hover:bg-bg-secondary transition-colors"
            >
              {copied === 'docs' ? <><Check size={11} className="text-success" /> Copied!</> : <><Copy size={11} /> Copy All for AI</>}
            </button>
          </div>

          {/* Auth section */}
          <div className="mb-8">
            <h3 className="font-heading text-sm font-semibold text-text-primary mb-2">Authentication</h3>
            <p className="text-xs text-text-secondary mb-3">Include your API token in the Authorization header:</p>
            <div className="relative bg-code-bg rounded-[8px] p-4">
              <pre className="text-xs font-mono text-text-primary overflow-x-auto">
{`curl -H "Authorization: Bearer <your-token>" \\
  ${baseUrl}/api/documents`}
              </pre>
              <button
                onClick={() => copyToClipboard(`curl -H "Authorization: Bearer <your-token>" ${baseUrl}/api/documents`, 'curl')}
                className="absolute top-2 right-2 p-1.5 hover:bg-bg-secondary rounded"
              >
                {copied === 'curl' ? <Check size={11} className="text-success" /> : <Copy size={11} className="text-text-tertiary" />}
              </button>
            </div>
          </div>

          {/* Endpoints */}
          {API_DOCS.map((group) => (
            <div key={group.group} className="mb-6">
              <h3 className="font-heading text-sm font-semibold text-text-primary mb-3">{group.group}</h3>
              <div className="flex flex-col gap-1">
                {group.endpoints.map((ep) => (
                  <div key={`${ep.method} ${ep.path}`} className="flex items-center gap-3 px-3 py-2 rounded-[6px] hover:bg-bg-secondary transition-colors">
                    <span className={cn('text-[9px] font-bold font-mono px-1.5 py-0.5 rounded w-12 text-center', METHOD_COLORS[ep.method] || '')}>
                      {ep.method}
                    </span>
                    <code className="text-xs font-mono text-text-primary">{ep.path}</code>
                    <span className="text-xs text-text-tertiary flex-1">{ep.desc}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* Swagger link */}
          <div className="mt-8 p-4 bg-bg-secondary rounded-[8px] border border-border flex items-center justify-between">
            <div>
              <h3 className="text-xs font-semibold text-text-primary">Interactive API Docs</h3>
              <p className="text-[10px] text-text-tertiary mt-0.5">Full Swagger UI with try-it-out</p>
            </div>
            <a
              href={`${baseUrl}/docs`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3 py-2 border border-border rounded-[6px] text-xs font-semibold text-text-secondary hover:bg-bg-tertiary transition-colors"
            >
              <ExternalLink size={12} /> Open Swagger
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
