import { useState, useEffect, useCallback, useRef } from 'react'
import { FolderOpen, File, Image, Trash2, ArrowRight, Upload, Plus, Save, Pencil } from 'lucide-react'
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

const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'])
function isImage(name: string): boolean {
  return IMAGE_EXTS.has(name.slice(name.lastIndexOf('.')).toLowerCase())
}
function isMarkdown(name: string): boolean {
  return name.endsWith('.md') || name.endsWith('.txt')
}

export function WorkspacePage() {
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [selected, setSelected] = useState<WorkspaceFile | null>(null)
  const [content, setContent] = useState('')
  const [editContent, setEditContent] = useState('')
  const [mode, setMode] = useState<'preview' | 'edit'>('preview')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [renamingPath, setRenamingPath] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameRef = useRef<HTMLInputElement>(null)

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
    setMode('preview')
    if (isImage(file.name)) {
      setContent('')
      return
    }
    try {
      const { data } = await api.get(`/api/workspace/${file.path}`)
      setContent(data.content || '')
      setEditContent(data.content || '')
    } catch {
      setContent('Failed to load file.')
    }
  }, [])

  const handleSave = useCallback(async () => {
    if (!selected) return
    setSaving(true)
    try {
      await api.put(`/api/workspace/${selected.path}`, { content: editContent })
      setContent(editContent)
      setMode('preview')
    } catch { /* silent */ }
    finally { setSaving(false) }
  }, [selected, editContent])

  const handleCreate = useCallback(async () => {
    const name = prompt('New file name (e.g. notes.md):')
    if (!name) return
    try {
      await api.post('/api/workspace', { name, content: `# ${name.replace('.md', '')}\n\n` })
      await fetchFiles()
    } catch { /* silent */ }
  }, [fetchFiles])

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadFiles = e.target.files
    if (!uploadFiles) return
    for (const file of Array.from(uploadFiles)) {
      const form = new FormData()
      form.append('file', file)
      await api.post('/api/workspace/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    }
    await fetchFiles()
    e.target.value = ''
  }, [fetchFiles])

  const handleIngest = useCallback(async (file: WorkspaceFile) => {
    if (!confirm(`Send "${file.name}" to ingest pipeline?\nIt will be classified and moved to knowledge/.`)) return
    try {
      await api.post(`/api/workspace/move-to-raw/${file.path}`)
      if (selected?.path === file.path) { setSelected(null); setContent('') }
      await fetchFiles()
    } catch { /* silent */ }
  }, [selected, fetchFiles])

  const handleDelete = useCallback(async (file: WorkspaceFile) => {
    if (!confirm(`Delete "${file.name}"?`)) return
    try {
      await api.delete(`/api/workspace/${file.path}`)
      if (selected?.path === file.path) { setSelected(null); setContent('') }
      await fetchFiles()
    } catch { /* silent */ }
  }, [selected, fetchFiles])

  const handleRename = useCallback(async (file: WorkspaceFile) => {
    if (!renameValue.trim() || renameValue === file.name) {
      setRenamingPath(null)
      return
    }
    try {
      const { data } = await api.put(`/api/workspace/${file.path}`, { name: renameValue })
      if (selected?.path === file.path) {
        setSelected({ ...selected, path: data.path, name: renameValue })
      }
      await fetchFiles()
    } catch { /* silent */ }
    setRenamingPath(null)
  }, [renameValue, selected, fetchFiles])

  const startRename = (file: WorkspaceFile) => {
    setRenamingPath(file.path)
    setRenameValue(file.name)
    setTimeout(() => renameRef.current?.focus(), 50)
  }

  // Build image URL for workspace images
  const token = localStorage.getItem('pagefly_token') || ''
  const imageUrl = selected ? `/api/workspace/${selected.path}?token=${token}` : ''

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <FolderOpen size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Workspace</h1>
          <span className="text-xs text-text-tertiary">{files.length} files</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCreate}
            className="flex items-center gap-1.5 px-3 py-2 border border-border rounded-[6px] text-xs font-semibold text-text-secondary hover:bg-bg-secondary transition-colors"
          >
            <Plus size={13} />
            New File
          </button>
          <label className="flex items-center gap-1.5 px-3 py-2 bg-accent-primary rounded-[8px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors cursor-pointer">
            <Upload size={13} />
            Upload
            <input type="file" className="hidden" multiple onChange={handleUpload} />
          </label>
        </div>
      </header>

      {/* Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* File list */}
        <aside className="w-[300px] border-r border-border flex-shrink-0 overflow-y-auto">
          <div className="p-3 flex flex-col gap-0.5">
            {loading ? (
              <p className="text-xs text-text-tertiary py-8 text-center">Loading...</p>
            ) : files.length === 0 ? (
              <div className="py-12 text-center">
                <FolderOpen size={32} className="text-text-tertiary mx-auto mb-3" />
                <p className="text-sm text-text-tertiary">Workspace is empty</p>
                <p className="text-xs text-text-tertiary mt-1">Create a file or upload to get started</p>
              </div>
            ) : (
              files.map((file) => (
                <div
                  key={file.path}
                  className={cn(
                    'group flex items-center gap-2 px-3 py-2 rounded-[8px] transition-colors',
                    selected?.path === file.path ? 'bg-bg-tertiary' : 'hover:bg-bg-secondary'
                  )}
                >
                  <button onClick={() => selectFile(file)} className="flex-1 flex items-center gap-2 min-w-0 text-left">
                    {isImage(file.name) ? (
                      <Image size={13} className="text-accent-warm flex-shrink-0" />
                    ) : (
                      <File size={13} className="text-text-tertiary flex-shrink-0" />
                    )}
                    <div className="flex flex-col min-w-0">
                      {renamingPath === file.path ? (
                        <input
                          ref={renameRef}
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onBlur={() => handleRename(file)}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleRename(file); if (e.key === 'Escape') setRenamingPath(null) }}
                          className="text-xs font-medium text-text-primary bg-bg-primary border border-accent-primary rounded px-1 py-0.5 outline-none w-full"
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <span className="text-xs font-medium text-text-primary truncate">{file.name}</span>
                      )}
                      <span className="text-[10px] text-text-tertiary">{formatSize(file.size)}</span>
                    </div>
                  </button>
                  <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                    <button onClick={() => startRename(file)} title="Rename" className="p-1 rounded hover:bg-bg-tertiary text-text-tertiary">
                      <Pencil size={11} />
                    </button>
                    {!isImage(file.name) && (
                      <button onClick={() => handleIngest(file)} title="Send to Ingest" className="p-1 rounded hover:bg-accent-primary/10 text-accent-secondary">
                        <ArrowRight size={11} />
                      </button>
                    )}
                    <button onClick={() => handleDelete(file)} title="Delete" className="p-1 rounded hover:bg-error/10 text-error">
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Preview / Editor */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {selected ? (
            <>
              <div className="flex items-center justify-between px-6 py-3 border-b border-border flex-shrink-0">
                <span className="text-xs font-medium text-text-primary">{selected.name}</span>
                <div className="flex items-center gap-2">
                  {isMarkdown(selected.name) && (
                    <>
                      {mode === 'edit' ? (
                        <button
                          onClick={handleSave}
                          disabled={saving}
                          className="flex items-center gap-1 px-3 py-1.5 bg-accent-primary rounded-[6px] text-[11px] font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60"
                        >
                          <Save size={11} />
                          {saving ? 'Saving...' : 'Save'}
                        </button>
                      ) : (
                        <button
                          onClick={() => { setEditContent(content); setMode('edit') }}
                          className="flex items-center gap-1 px-3 py-1.5 border border-border rounded-[6px] text-[11px] font-semibold text-text-secondary hover:bg-bg-secondary transition-colors"
                        >
                          <Pencil size={11} />
                          Edit
                        </button>
                      )}
                    </>
                  )}
                  {!isImage(selected.name) && (
                    <button
                      onClick={() => handleIngest(selected)}
                      className="flex items-center gap-1 px-3 py-1.5 border border-accent-primary rounded-[6px] text-[11px] font-semibold text-accent-primary hover:bg-accent-primary hover:text-bg-primary transition-colors"
                    >
                      <ArrowRight size={11} />
                      Ingest
                    </button>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto">
                {isImage(selected.name) ? (
                  <div className="p-6 flex items-start justify-center">
                    <img src={imageUrl} alt={selected.name} className="max-w-full rounded-[8px] shadow-sm" />
                  </div>
                ) : mode === 'edit' ? (
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="w-full h-full p-6 bg-bg-primary text-text-primary text-sm font-mono leading-relaxed outline-none resize-none"
                    spellCheck={false}
                  />
                ) : isMarkdown(selected.name) ? (
                  <article className="px-8 py-6 prose-pagefly">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                  </article>
                ) : (
                  <pre className="px-6 py-4 text-xs font-mono text-text-secondary whitespace-pre-wrap leading-relaxed">{content}</pre>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-text-tertiary gap-2">
              <FolderOpen size={40} className="opacity-30" />
              <p className="text-sm">Select a file or create a new one</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
