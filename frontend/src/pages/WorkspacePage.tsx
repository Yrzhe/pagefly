import { useState, useEffect, useCallback } from 'react'
import { FolderOpen, File, Trash2, ArrowRight, Upload, Eye } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface WorkspaceFile {
  path: string
  name: string
  size: number
  modified: number
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString()
}

export function WorkspacePage() {
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [selected, setSelected] = useState<WorkspaceFile | null>(null)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const fetchFiles = useCallback(async () => {
    try {
      const { data } = await api.get('/api/workspace')
      setFiles(data.files || [])
    } catch {
      setFiles([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchFiles() }, [fetchFiles])

  const selectFile = useCallback(async (file: WorkspaceFile) => {
    setSelected(file)
    try {
      const { data } = await api.get(`/api/workspace/${file.path}`)
      setContent(data.content || '')
    } catch {
      setContent('Failed to load file.')
    }
  }, [])

  const handleMoveToRaw = useCallback(async (file: WorkspaceFile) => {
    if (!confirm(`Move "${file.name}" to ingest pipeline? It will be classified and moved to knowledge/.`)) return
    setActionLoading(file.path)
    try {
      await api.post(`/api/workspace/move-to-raw/${file.path}`)
      if (selected?.path === file.path) {
        setSelected(null)
        setContent('')
      }
      await fetchFiles()
    } catch { /* silent */ }
    finally { setActionLoading(null) }
  }, [selected, fetchFiles])

  const handleDelete = useCallback(async (file: WorkspaceFile) => {
    if (!confirm(`Delete "${file.name}"? This cannot be undone.`)) return
    setActionLoading(file.path)
    try {
      await api.delete(`/api/workspace/${file.path}`)
      if (selected?.path === file.path) {
        setSelected(null)
        setContent('')
      }
      await fetchFiles()
    } catch { /* silent */ }
    finally { setActionLoading(null) }
  }, [selected, fetchFiles])

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    try {
      await api.post('/api/ingest', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      await fetchFiles()
    } catch { /* silent */ }
    e.target.value = ''
  }, [fetchFiles])

  const isMarkdown = selected?.name.endsWith('.md') || selected?.name.endsWith('.txt')

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <FolderOpen size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Workspace</h1>
          <span className="text-xs text-text-tertiary">{files.length} files</span>
        </div>
        <label className="flex items-center gap-1.5 px-4 py-2 bg-accent-primary rounded-[8px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors cursor-pointer">
          <Upload size={13} />
          Upload to Ingest
          <input type="file" className="hidden" onChange={handleUpload} />
        </label>
      </header>

      {/* Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* File list */}
        <aside className="w-[320px] border-r border-border flex-shrink-0 overflow-y-auto">
          <div className="p-3 flex flex-col gap-0.5">
            {loading ? (
              <p className="text-xs text-text-tertiary py-8 text-center">Loading...</p>
            ) : files.length === 0 ? (
              <div className="py-12 text-center">
                <FolderOpen size={32} className="text-text-tertiary mx-auto mb-3" />
                <p className="text-sm text-text-tertiary">Workspace is empty</p>
                <p className="text-xs text-text-tertiary mt-1">Agent will place files here during work</p>
              </div>
            ) : (
              files.map((file) => (
                <div
                  key={file.path}
                  className={cn(
                    'group flex items-center gap-3 px-3 py-2.5 rounded-[8px] transition-colors',
                    selected?.path === file.path ? 'bg-bg-tertiary' : 'hover:bg-bg-secondary'
                  )}
                >
                  <button
                    onClick={() => selectFile(file)}
                    className="flex-1 flex items-center gap-2.5 min-w-0 text-left"
                  >
                    <File size={14} className="text-text-tertiary flex-shrink-0" />
                    <div className="flex flex-col min-w-0">
                      <span className="text-xs font-medium text-text-primary truncate">{file.name}</span>
                      <span className="text-[10px] text-text-tertiary">{formatSize(file.size)} · {formatDate(file.modified)}</span>
                    </div>
                  </button>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => handleMoveToRaw(file)}
                      disabled={actionLoading === file.path}
                      title="Move to ingest pipeline"
                      className="p-1.5 rounded hover:bg-accent-primary/10 text-accent-secondary"
                    >
                      <ArrowRight size={12} />
                    </button>
                    <button
                      onClick={() => handleDelete(file)}
                      disabled={actionLoading === file.path}
                      title="Delete"
                      className="p-1.5 rounded hover:bg-error/10 text-error"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Preview */}
        <div className="flex-1 overflow-y-auto">
          {selected ? (
            <div className="flex flex-col h-full">
              <div className="flex items-center justify-between px-6 py-3 border-b border-border flex-shrink-0">
                <div className="flex items-center gap-2">
                  <Eye size={13} className="text-text-tertiary" />
                  <span className="text-xs font-medium text-text-primary">{selected.name}</span>
                  <span className="text-[10px] text-text-tertiary">{formatSize(selected.size)}</span>
                </div>
                <button
                  onClick={() => handleMoveToRaw(selected)}
                  disabled={actionLoading === selected.path}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-accent-primary rounded-[6px] text-[11px] font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60"
                >
                  <ArrowRight size={12} />
                  Send to Ingest
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                {isMarkdown ? (
                  <article className="px-8 py-6 prose-pagefly">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                  </article>
                ) : (
                  <pre className="px-6 py-4 text-xs font-mono text-text-secondary whitespace-pre-wrap leading-relaxed">
                    {content}
                  </pre>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-text-tertiary text-sm">
              Select a file to preview
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
