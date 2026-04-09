import { useState, useEffect, useCallback, useRef } from 'react'
import { FolderOpen, Trash2, ArrowRight, Plus, Save, Pencil, Image as ImageIcon, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface WorkspaceFolder {
  name: string
  size: number
  modified: number
  image_count: number
}

interface WSImage {
  name: string
  size: number
}

export function WorkspacePage() {
  const [folders, setFolders] = useState<WorkspaceFolder[]>([])
  const [selected, setSelected] = useState<WorkspaceFolder | null>(null)
  const [content, setContent] = useState('')
  const [editContent, setEditContent] = useState('')
  const [images, setImages] = useState<WSImage[]>([])
  const [mode, setMode] = useState<'preview' | 'edit'>('preview')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [renamingName, setRenamingName] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [showImages, setShowImages] = useState(false)
  const renameRef = useRef<HTMLInputElement>(null)
  const token = localStorage.getItem('pagefly_token') || ''

  const fetchFolders = useCallback(async () => {
    try {
      const { data } = await api.get('/api/workspace')
      setFolders(data.folders || [])
    } catch { setFolders([]) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchFolders() }, [fetchFolders])

  const selectFolder = useCallback(async (folder: WorkspaceFolder) => {
    setSelected(folder)
    setMode('preview')
    setShowImages(false)
    try {
      const [contentRes, imagesRes] = await Promise.all([
        api.get(`/api/workspace/${folder.name}/content`),
        api.get(`/api/workspace/${folder.name}/images`),
      ])
      setContent(contentRes.data.content || '')
      setEditContent(contentRes.data.content || '')
      setImages(imagesRes.data.images || [])
    } catch {
      setContent('Failed to load.')
      setImages([])
    }
  }, [])

  const handleSave = useCallback(async () => {
    if (!selected) return
    setSaving(true)
    try {
      await api.put(`/api/workspace/${selected.name}/content`, { content: editContent })
      setContent(editContent)
      setMode('preview')
    } catch { /* silent */ }
    finally { setSaving(false) }
  }, [selected, editContent])

  const handleCreate = useCallback(async () => {
    const name = prompt('New document name:')
    if (!name) return
    try {
      const { data } = await api.post('/api/workspace', { name })
      await fetchFolders()
      selectFolder({ name: data.name, size: 0, modified: Date.now() / 1000, image_count: 0 })
    } catch { /* silent */ }
  }, [fetchFolders, selectFolder])

  const handleIngest = useCallback(async (folder: WorkspaceFolder) => {
    if (!confirm(`Send "${folder.name}" to ingest pipeline?\nIt will be classified (with images) and moved to knowledge/.`)) return
    try {
      await api.post(`/api/workspace/${folder.name}/ingest`)
      if (selected?.name === folder.name) { setSelected(null); setContent('') }
      await fetchFolders()
    } catch { /* silent */ }
  }, [selected, fetchFolders])

  const handleDelete = useCallback(async (folder: WorkspaceFolder) => {
    if (!confirm(`Delete "${folder.name}" and all its images?`)) return
    try {
      await api.delete(`/api/workspace/${folder.name}`)
      if (selected?.name === folder.name) { setSelected(null); setContent('') }
      await fetchFolders()
    } catch { /* silent */ }
  }, [selected, fetchFolders])

  const handleRename = useCallback(async (folder: WorkspaceFolder) => {
    if (!renameValue.trim() || renameValue === folder.name) { setRenamingName(null); return }
    try {
      const { data } = await api.put(`/api/workspace/${folder.name}`, { name: renameValue })
      if (selected?.name === folder.name) {
        setSelected({ ...selected, name: data.name })
      }
      await fetchFolders()
    } catch { /* silent */ }
    setRenamingName(null)
  }, [renameValue, selected, fetchFolders])

  const handleUploadImage = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selected || !e.target.files?.[0]) return
    const file = e.target.files[0]
    const form = new FormData()
    form.append('file', file)
    try {
      const { data } = await api.post(`/api/workspace/${selected.name}/images`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      // Insert markdown reference at cursor or end
      const ref = `\n${data.markdown}\n`
      setEditContent((prev) => prev + ref)
      setContent((prev) => prev + ref)
      // Refresh images
      const imgRes = await api.get(`/api/workspace/${selected.name}/images`)
      setImages(imgRes.data.images || [])
    } catch { /* silent */ }
    e.target.value = ''
  }, [selected])

  const handleDeleteImage = useCallback(async (imgName: string) => {
    if (!selected || !confirm(`Delete image "${imgName}"?`)) return
    try {
      await api.delete(`/api/workspace/${selected.name}/images/${imgName}`)
      setImages((prev) => prev.filter((i) => i.name !== imgName))
    } catch { /* silent */ }
  }, [selected])

  // Rewrite relative image paths for preview
  const previewContent = selected
    ? content.replace(
        /!\[([^\]]*)\]\(images\/([^)]+)\)/g,
        (_, alt, img) => `![${alt}](/api/workspace/${selected.name}/images/${img}?token=${token})`
      )
    : ''

  return (
    <div className="flex flex-col h-screen">
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <FolderOpen size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Workspace</h1>
          <span className="text-xs text-text-tertiary">{folders.length} documents</span>
        </div>
        <button onClick={handleCreate} className="flex items-center gap-1.5 px-4 py-2 bg-accent-primary rounded-[8px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors">
          <Plus size={13} /> New Document
        </button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Folder list */}
        <aside className="w-[280px] border-r border-border flex-shrink-0 overflow-y-auto">
          <div className="p-3 flex flex-col gap-0.5">
            {loading ? (
              <p className="text-xs text-text-tertiary py-8 text-center">Loading...</p>
            ) : folders.length === 0 ? (
              <div className="py-12 text-center">
                <FolderOpen size={32} className="text-text-tertiary mx-auto mb-3" />
                <p className="text-sm text-text-tertiary">No documents yet</p>
                <p className="text-xs text-text-tertiary mt-1">Click "New Document" to start writing</p>
              </div>
            ) : (
              folders.map((f) => (
                <div key={f.name} className={cn('group flex items-center gap-2 px-3 py-2.5 rounded-[8px] transition-colors', selected?.name === f.name ? 'bg-bg-tertiary' : 'hover:bg-bg-secondary')}>
                  <button onClick={() => selectFolder(f)} className="flex-1 flex items-center gap-2.5 min-w-0 text-left">
                    <FolderOpen size={13} className="text-accent-warm flex-shrink-0" />
                    <div className="flex flex-col min-w-0">
                      {renamingName === f.name ? (
                        <input ref={renameRef} value={renameValue} onChange={(e) => setRenameValue(e.target.value)}
                          onBlur={() => handleRename(f)} onKeyDown={(e) => { if (e.key === 'Enter') handleRename(f); if (e.key === 'Escape') setRenamingName(null) }}
                          className="text-xs font-medium text-text-primary bg-bg-primary border border-accent-primary rounded px-1 py-0.5 outline-none w-full"
                          onClick={(e) => e.stopPropagation()} />
                      ) : (
                        <span className="text-xs font-medium text-text-primary truncate">{f.name}</span>
                      )}
                      <span className="text-[10px] text-text-tertiary">
                        {f.image_count > 0 && `${f.image_count} images · `}
                        {(f.size / 1024).toFixed(1)} KB
                      </span>
                    </div>
                  </button>
                  <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                    <button onClick={() => { setRenamingName(f.name); setRenameValue(f.name); setTimeout(() => renameRef.current?.focus(), 50) }} title="Rename" className="p-1 rounded hover:bg-bg-tertiary text-text-tertiary"><Pencil size={10} /></button>
                    <button onClick={() => handleIngest(f)} title="Ingest" className="p-1 rounded hover:bg-accent-primary/10 text-accent-secondary"><ArrowRight size={10} /></button>
                    <button onClick={() => handleDelete(f)} title="Delete" className="p-1 rounded hover:bg-error/10 text-error"><Trash2 size={10} /></button>
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Editor / Preview */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {selected ? (
            <>
              <div className="flex items-center justify-between px-6 py-3 border-b border-border flex-shrink-0">
                <span className="text-xs font-medium text-text-primary">{selected.name}</span>
                <div className="flex items-center gap-2">
                  {saving && <span className="text-[10px] text-accent-primary">Saving...</span>}
                  {mode === 'edit' ? (
                    <>
                      <label className="flex items-center gap-1 px-2.5 py-1.5 border border-border rounded-[6px] text-[11px] text-text-secondary hover:bg-bg-secondary transition-colors cursor-pointer">
                        <ImageIcon size={11} /> Image
                        <input type="file" className="hidden" accept="image/*" onChange={handleUploadImage} />
                      </label>
                      <button onClick={handleSave} disabled={saving} className="flex items-center gap-1 px-3 py-1.5 bg-accent-primary rounded-[6px] text-[11px] font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60">
                        <Save size={11} /> Save
                      </button>
                    </>
                  ) : (
                    <button onClick={() => { setEditContent(content); setMode('edit') }} className="flex items-center gap-1 px-3 py-1.5 border border-border rounded-[6px] text-[11px] font-semibold text-text-secondary hover:bg-bg-secondary transition-colors">
                      <Pencil size={11} /> Edit
                    </button>
                  )}
                  <button onClick={() => setShowImages(!showImages)} className={cn('flex items-center gap-1 px-2.5 py-1.5 border rounded-[6px] text-[11px] transition-colors', showImages ? 'border-accent-primary text-accent-primary' : 'border-border text-text-secondary hover:bg-bg-secondary')}>
                    <ImageIcon size={11} /> {images.length}
                  </button>
                  <button onClick={() => handleIngest(selected)} className="flex items-center gap-1 px-3 py-1.5 border border-accent-primary rounded-[6px] text-[11px] font-semibold text-accent-primary hover:bg-accent-primary hover:text-bg-primary transition-colors">
                    <ArrowRight size={11} /> Ingest
                  </button>
                </div>
              </div>
              <div className="flex flex-1 overflow-hidden">
                <div className="flex-1 overflow-y-auto">
                  {mode === 'edit' ? (
                    <textarea value={editContent} onChange={(e) => setEditContent(e.target.value)} className="w-full h-full p-6 bg-bg-primary text-text-primary text-sm font-mono leading-relaxed outline-none resize-none" spellCheck={false} />
                  ) : (
                    <article className="px-8 py-6 prose-pagefly">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{previewContent}</ReactMarkdown>
                    </article>
                  )}
                </div>
                {/* Image panel */}
                {showImages && (
                  <aside className="w-[220px] border-l border-border overflow-y-auto p-3 flex flex-col gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-text-tertiary">Images ({images.length})</span>
                    {images.length === 0 ? (
                      <p className="text-[10px] text-text-tertiary">No images. Upload one in Edit mode.</p>
                    ) : images.map((img) => (
                      <div key={img.name} className="group relative rounded-[6px] overflow-hidden border border-border">
                        <img src={`/api/workspace/${selected.name}/images/${img.name}?token=${token}`} alt={img.name} className="w-full" />
                        <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button onClick={() => handleDeleteImage(img.name)} className="p-1 bg-error/90 rounded text-white"><X size={10} /></button>
                        </div>
                        <div className="px-2 py-1 text-[9px] text-text-tertiary truncate">{img.name}</div>
                      </div>
                    ))}
                  </aside>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-text-tertiary gap-2">
              <FolderOpen size={40} className="opacity-30" />
              <p className="text-sm">Select a document or create a new one</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
