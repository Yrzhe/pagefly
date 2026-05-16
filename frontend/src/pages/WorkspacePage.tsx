import { useState, useEffect, useCallback, useRef } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import CharacterCount from '@tiptap/extension-character-count'
import Image from '@tiptap/extension-image'
import { Table } from '@tiptap/extension-table'
import { TableRow } from '@tiptap/extension-table-row'
import { TableHeader } from '@tiptap/extension-table-header'
import { TableCell } from '@tiptap/extension-table-cell'
import {
  PenTool,
  Plus,
  Trash2,
  Save,
  Bold,
  Italic,
  Strikethrough,
  Code,
  CodeSquare,
  List,
  ListOrdered,
  Quote,
  Minus,
  Undo2,
  Redo2,
  Heading1,
  Heading2,
  Heading3,
  ImageIcon,
  TableIcon,
  Link,
  Upload,
  RowsIcon,
  ColumnsIcon,
  ArrowRight,
  CheckCircle,
  FileText,
  MessageSquare,
  Send,
  X,
  Loader2,
} from 'lucide-react'
import api from '@/api/client'
import { cn } from '@/lib/utils'
import { SuggestionBar, type PendingSuggestion } from '@/components/workspace/SuggestionBar'

interface WsDoc {
  id: string
  title: string
  status: string
  revision: number
  created_by: string
  created_at: string
  updated_at: string
}

interface WsDocFull extends WsDoc {
  content: string
}

export function WorkspacePage() {
  const [docs, setDocs] = useState<WsDoc[]>([])
  const [selected, setSelected] = useState<WsDocFull | null>(null)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [chatOpen, setChatOpen] = useState(false)
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string; ts?: string }[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const [pending, setPending] = useState<PendingSuggestion | null>(null)

  const fetchPending = useCallback(async (docId: string) => {
    try {
      const { data } = await api.get(`/api/workspace/documents/${docId}/suggestions`)
      setPending(data.pending || null)
    } catch {
      setPending(null)
    }
  }, [])


  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: 'Start writing...' }),
      CharacterCount,
      Image.configure({ inline: true, allowBase64: true }),
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
    ],
    content: '',
    editorProps: {
      attributes: {
        class: 'prose-pagefly outline-none min-h-[60vh] px-8 py-6',
      },
    },
  })

  const fetchDocs = useCallback(async () => {
    try {
      const { data } = await api.get('/api/workspace/documents')
      setDocs(data.documents || [])
    } catch { setDocs([]) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchDocs() }, [fetchDocs])

  const handleSuggestionResolved = useCallback(async (docId: string, action: 'accept' | 'reject') => {
    setPending(null)
    if (action === 'accept') {
      // Accepted edits changed the document — reload content + revision.
      try {
        const { data } = await api.get(`/api/workspace/documents/${docId}`)
        setSelected(data)
        editor?.commands.setContent(data.content || '<p></p>')
        fetchDocs()
      } catch { /* keep current view */ }
    }
  }, [editor, fetchDocs])

  const selectDoc = useCallback(async (doc: WsDoc) => {
    // Save current doc before switching
    await handleSaveRef.current()
    try {
      const { data } = await api.get(`/api/workspace/documents/${doc.id}`)
      setSelected(data)
      setTitle(data.title)
      setError('')
      editor?.commands.setContent(data.content || '<p></p>')
      fetchPending(data.id)
      // Load chat history from main shared session
      try {
        const { data: chatData } = await api.get('/api/chat/history')
        setChatMessages(chatData.messages || [])
      } catch { setChatMessages([]) }
    } catch {
      setError('Failed to load document')
    }
  }, [editor, fetchPending])

  const handleCreate = async () => {
    const name = prompt('Document title:')
    if (!name?.trim()) return
    try {
      const { data } = await api.post('/api/workspace/documents', { title: name })
      await fetchDocs()
      // Select the newly created doc
      const { data: full } = await api.get(`/api/workspace/documents/${data.id}`)
      setSelected(full)
      setTitle(full.title)
      setPending(null)
      editor?.commands.setContent('<p></p>')
    } catch { /* silent */ }
  }

  const handleSave = useCallback(async () => {
    if (!selected || !editor) return
    const html = editor.getHTML()
    // Skip save if nothing changed
    if (html === selected.content && title === selected.title) return
    setSaving(true)
    setError('')
    try {
      const { data } = await api.patch(`/api/workspace/documents/${selected.id}`, {
        title,
        content: html,
        revision: selected.revision,
      })
      setSelected((prev) => prev ? { ...prev, revision: data.revision, title, content: html } : prev)
      fetchDocs()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [selected, editor, title, fetchDocs])

  // Auto-save: debounce 2s after editor changes
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleSaveRef = useRef(handleSave)
  handleSaveRef.current = handleSave

  useEffect(() => {
    if (!editor) return
    const onUpdate = () => {
      if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current)
      autoSaveTimer.current = setTimeout(() => handleSaveRef.current(), 2000)
    }
    editor.on('update', onUpdate)
    return () => { editor.off('update', onUpdate); if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current) }
  }, [editor])

  // Auto-save on title change (debounced)
  useEffect(() => {
    if (!selected) return
    const t = setTimeout(() => handleSaveRef.current(), 2000)
    return () => clearTimeout(t)
  }, [title, selected])

  // Save before switching docs or leaving page
  useEffect(() => {
    const onBeforeUnload = () => { handleSaveRef.current() }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [])

  const handleStatusChange = useCallback(async (newStatus: string) => {
    if (!selected) return
    try {
      const { data } = await api.patch(`/api/workspace/documents/${selected.id}`, {
        status: newStatus,
        revision: selected.revision,
      })
      setSelected((prev) => prev ? { ...prev, status: newStatus, revision: data.revision } : prev)
      fetchDocs()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Status update failed')
    }
  }, [selected, fetchDocs])

  const handleIngest = useCallback(async () => {
    if (!selected || selected.status !== 'finished') return
    if (!confirm(`Ingest "${selected.title}" into knowledge base?\nThe document will be classified and archived.`)) return
    try {
      await api.post(`/api/workspace/documents/${selected.id}/ingest`)
      setSelected(null)
      setPending(null)
      editor?.commands.setContent('')
      fetchDocs()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Ingest failed')
    }
  }, [selected, editor, fetchDocs])

  const handleDelete = useCallback(async (doc: WsDoc) => {
    if (!confirm(`Delete "${doc.title}"?`)) return
    try {
      await api.delete(`/api/workspace/documents/${doc.id}`)
      if (selected?.id === doc.id) {
        setSelected(null)
        setPending(null)
        editor?.commands.setContent('')
      }
      fetchDocs()
    } catch { /* silent */ }
  }, [selected, editor, fetchDocs])

  // Ctrl+S
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        handleSave()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleSave])

  // Chat send
  const handleChatSend = useCallback(async () => {
    if (!selected || !chatInput.trim() || chatLoading) return
    const msg = chatInput.trim()
    setChatInput('')
    // Show user message immediately (without prefix)
    setChatMessages((prev) => [...prev, { role: 'user', content: msg }])
    setChatLoading(true)
    try {
      // Prefix message with workspace document context so agent knows what we're editing
      const prefixedMsg = `[正在编辑 Workspace 文档: ${selected.id} "${selected.title}"]\n${msg}`
      const { data } = await api.post('/api/chat', { message: prefixedMsg })
      setChatMessages(data.messages || [])
      // The agent may have staged a pending suggestion via its tool.
      fetchPending(selected.id)
    } catch {
      setChatMessages((prev) => [...prev, { role: 'assistant', content: 'Error: failed to get response.' }])
    } finally {
      setChatLoading(false)
    }
  }, [selected, chatInput, chatLoading, fetchPending])

  // Scroll chat to bottom on new messages, loading state change, or panel open
  useEffect(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }, [chatMessages, chatLoading, chatOpen])

  const charCount = editor?.storage.characterCount?.characters() ?? 0
  const wordCount = editor?.storage.characterCount?.words() ?? 0
  const isInTable = editor?.isActive('table') ?? false

  const fmtDate = (iso: string) => {
    try { return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
    catch { return iso }
  }

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <PenTool size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Workspace</h1>
          <span className="text-xs text-text-tertiary">{docs.length} documents</span>
        </div>
        <button onClick={handleCreate} className="flex items-center gap-1.5 px-4 py-2 bg-accent-primary rounded-[8px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors">
          <Plus size={13} /> New Document
        </button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Document list */}
        <aside className="w-[260px] border-r border-border flex-shrink-0 overflow-y-auto">
          <div className="p-3 flex flex-col gap-0.5">
            {loading ? (
              <p className="text-xs text-text-tertiary py-8 text-center">Loading...</p>
            ) : docs.length === 0 ? (
              <div className="py-12 text-center">
                <FileText size={32} className="text-text-tertiary mx-auto mb-3 opacity-40" />
                <p className="text-sm text-text-tertiary">No documents yet</p>
                <p className="text-xs text-text-tertiary mt-1">Click "New Document" to start</p>
              </div>
            ) : (
              docs.map((d) => (
                <div
                  key={d.id}
                  className={cn(
                    'group flex items-center gap-2 px-3 py-2.5 rounded-[8px] transition-colors cursor-pointer',
                    selected?.id === d.id ? 'bg-bg-tertiary' : 'hover:bg-bg-secondary'
                  )}
                >
                  <button onClick={() => selectDoc(d)} className="flex-1 flex items-center gap-2.5 min-w-0 text-left">
                    <FileText size={13} className="text-accent-warm flex-shrink-0" />
                    <div className="flex flex-col min-w-0">
                      <span className="text-xs font-medium text-text-primary truncate">{d.title || '(untitled)'}</span>
                      <span className="text-[10px] text-text-tertiary">
                        <StatusBadge status={d.status} /> · rev {d.revision} · {fmtDate(d.updated_at)}
                      </span>
                    </div>
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(d) }}
                    className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-error/10 text-text-tertiary hover:text-error transition-all flex-shrink-0"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Editor panel */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {selected ? (
            <>
              {/* Doc header bar */}
              <div className="flex items-center justify-between px-6 py-2.5 border-b border-border flex-shrink-0">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Untitled"
                    className="text-sm font-heading font-bold text-text-primary bg-transparent outline-none border-none flex-1 min-w-0"
                  />
                  <StatusBadgeColored status={selected.status} />
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {error && <span className="text-[10px] text-error max-w-[200px] truncate">{error}</span>}
                  <span className="text-[10px] text-text-tertiary">
                    rev {selected.revision} · {charCount}c · {wordCount}w
                  </span>

                  {/* Status actions */}
                  {selected.status === 'draft' && (
                    <button
                      onClick={() => handleStatusChange('finished')}
                      className="flex items-center gap-1 px-2.5 py-1.5 border border-green-400 rounded-[6px] text-[11px] font-medium text-green-600 hover:bg-green-50 transition-colors"
                    >
                      <CheckCircle size={11} /> Mark Finished
                    </button>
                  )}
                  {selected.status === 'finished' && (
                    <>
                      <button
                        onClick={() => handleStatusChange('draft')}
                        className="flex items-center gap-1 px-2.5 py-1.5 border border-border rounded-[6px] text-[11px] text-text-secondary hover:bg-bg-secondary transition-colors"
                      >
                        Back to Draft
                      </button>
                      <button
                        onClick={handleIngest}
                        className="flex items-center gap-1 px-3 py-1.5 bg-green-600 rounded-[6px] text-[11px] font-semibold text-white hover:bg-green-700 transition-colors"
                      >
                        <ArrowRight size={11} /> Ingest
                      </button>
                    </>
                  )}

                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="flex items-center gap-1 px-3 py-1.5 bg-accent-primary rounded-[6px] text-[11px] font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60"
                  >
                    <Save size={11} /> {saving ? 'Saving...' : 'Save'}
                  </button>
                  <button
                    onClick={() => setChatOpen(!chatOpen)}
                    className={cn(
                      'flex items-center gap-1 px-3 py-1.5 rounded-[6px] text-[11px] font-medium transition-colors',
                      chatOpen ? 'bg-accent-primary text-bg-primary' : 'border border-border text-text-secondary hover:bg-bg-secondary'
                    )}
                  >
                    <MessageSquare size={11} /> AI
                  </button>
                </div>
              </div>

              {/* Pending AI suggestion */}
              {pending && (
                <SuggestionBar
                  docId={selected.id}
                  suggestion={pending}
                  onResolved={(action) => handleSuggestionResolved(selected.id, action)}
                />
              )}

              {/* Toolbar */}
              {editor && (
                <div className="flex items-center gap-0.5 px-4 py-1.5 border-b border-border flex-shrink-0 flex-wrap bg-bg-primary relative z-20">
                  <TBtn onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} active={editor.isActive('heading', { level: 1 })} icon={<Heading1 size={14} />} title="Heading 1" />
                  <TBtn onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive('heading', { level: 2 })} icon={<Heading2 size={14} />} title="Heading 2" />
                  <TBtn onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} active={editor.isActive('heading', { level: 3 })} icon={<Heading3 size={14} />} title="Heading 3" />
                  <Sep />
                  <TBtn onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive('bold')} icon={<Bold size={14} />} title="Bold (Ctrl+B)" />
                  <TBtn onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive('italic')} icon={<Italic size={14} />} title="Italic (Ctrl+I)" />
                  <TBtn onClick={() => editor.chain().focus().toggleStrike().run()} active={editor.isActive('strike')} icon={<Strikethrough size={14} />} title="Strikethrough" />
                  <TBtn onClick={() => editor.chain().focus().toggleCode().run()} active={editor.isActive('code')} icon={<Code size={14} />} title="Inline Code" />
                  <TBtn onClick={() => editor.chain().focus().toggleCodeBlock().run()} active={editor.isActive('codeBlock')} icon={<CodeSquare size={14} />} title="Code Block" />
                  <Sep />
                  <TBtn onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive('bulletList')} icon={<List size={14} />} title="Bullet List" />
                  <TBtn onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive('orderedList')} icon={<ListOrdered size={14} />} title="Ordered List" />
                  <TBtn onClick={() => editor.chain().focus().toggleBlockquote().run()} active={editor.isActive('blockquote')} icon={<Quote size={14} />} title="Blockquote" />
                  <TBtn onClick={() => editor.chain().focus().setHorizontalRule().run()} icon={<Minus size={14} />} title="Horizontal Rule" />
                  <Sep />
                  <ImageInsertButton editor={editor} />
                  <TableInsertButton editor={editor} />
                  {isInTable && (
                    <>
                      <Sep />
                      <TBtn onClick={() => editor.chain().focus().addRowAfter().run()} icon={<><RowsIcon size={12} /><Plus size={8} /></>} title="Add Row" />
                      <TBtn onClick={() => editor.chain().focus().addColumnAfter().run()} icon={<><ColumnsIcon size={12} /><Plus size={8} /></>} title="Add Column" />
                      <TBtn onClick={() => editor.chain().focus().deleteRow().run()} icon={<><RowsIcon size={12} /><Minus size={8} /></>} title="Delete Row" />
                      <TBtn onClick={() => editor.chain().focus().deleteColumn().run()} icon={<><ColumnsIcon size={12} /><Minus size={8} /></>} title="Delete Column" />
                      <TBtn onClick={() => editor.chain().focus().deleteTable().run()} icon={<Trash2 size={12} />} title="Delete Table" />
                    </>
                  )}
                  <Sep />
                  <TBtn onClick={() => editor.chain().focus().undo().run()} disabled={!editor.can().undo()} icon={<Undo2 size={14} />} title="Undo" />
                  <TBtn onClick={() => editor.chain().focus().redo().run()} disabled={!editor.can().redo()} icon={<Redo2 size={14} />} title="Redo" />
                </div>
              )}

              {/* Editor + Chat Panel */}
              <div className="flex flex-1 overflow-hidden">
                <div className="flex-1 overflow-y-auto">
                  <div className="max-w-[780px] mx-auto">
                    <EditorContent editor={editor} />
                  </div>
                </div>

                {/* AI Chat Panel */}
                {chatOpen && (
                  <aside className="w-[320px] border-l border-border flex flex-col flex-shrink-0 bg-bg-primary overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                      <div className="flex items-center gap-2">
                        <MessageSquare size={13} className="text-accent-primary" />
                        <span className="text-xs font-bold text-text-primary">AI Assistant</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => { if (confirm('Clear all chat history?')) { api.post('/api/chat/reset'); setChatMessages([]) } }}
                          className="p-1 rounded text-text-tertiary hover:text-error hover:bg-error/10 transition-colors"
                          title="Clear chat"
                        >
                          <Trash2 size={11} />
                        </button>
                        <button onClick={() => setChatOpen(false)} className="p-1 rounded text-text-tertiary hover:text-text-primary hover:bg-bg-secondary transition-colors">
                          <X size={13} />
                        </button>
                      </div>
                    </div>

                    {/* Messages */}
                    <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
                      {chatMessages.length === 0 && !chatLoading && (
                        <div className="text-center py-8">
                          <MessageSquare size={24} className="text-text-tertiary mx-auto mb-2 opacity-30" />
                          <p className="text-xs text-text-tertiary">Ask AI about this document</p>
                          <p className="text-[10px] text-text-tertiary mt-1">e.g. "Improve the introduction" or "What's missing?"</p>
                        </div>
                      )}
                      {chatMessages.map((m, i) => (
                        <div key={i} className={cn('max-w-[95%] text-xs leading-relaxed min-w-0', m.role === 'user' ? 'ml-auto' : 'mr-auto')}>
                          <div className={cn(
                            'px-3 py-2 rounded-lg whitespace-pre-wrap break-words overflow-hidden',
                            m.role === 'user'
                              ? 'bg-accent-primary/10 text-text-primary rounded-br-sm'
                              : 'bg-bg-secondary text-text-primary rounded-bl-sm'
                          )}>
                            {m.content}
                          </div>
                        </div>
                      ))}
                      {chatLoading && (
                        <div className="flex items-center gap-2 text-xs text-text-tertiary mr-auto">
                          <Loader2 size={12} className="animate-spin" />
                          Thinking...
                        </div>
                      )}
                      <div ref={chatEndRef} />
                    </div>

                    {/* Input */}
                    <div className="p-3 border-t border-border">
                      <div className="flex gap-2">
                        <input
                          value={chatInput}
                          onChange={(e) => setChatInput(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChatSend() } }}
                          placeholder="Ask about this document..."
                          className="flex-1 px-3 py-2 text-xs bg-bg-secondary border border-border rounded-lg text-text-primary outline-none focus:border-accent-primary transition-colors"
                          disabled={chatLoading}
                        />
                        <button
                          onClick={handleChatSend}
                          disabled={chatLoading || !chatInput.trim()}
                          className="p-2 bg-accent-primary rounded-lg text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-40"
                        >
                          <Send size={13} />
                        </button>
                      </div>
                    </div>
                  </aside>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-text-tertiary gap-2">
              <PenTool size={40} className="opacity-20" />
              <p className="text-sm">Select a document or create a new one</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Small components ── */

function StatusBadge({ status }: { status: string }) {
  return <span className="uppercase text-[9px] font-bold">{status}</span>
}

function StatusBadgeColored({ status }: { status: string }) {
  return (
    <span className={cn(
      'text-[10px] px-2 py-0.5 rounded-full font-medium',
      status === 'draft' ? 'bg-amber-100 text-amber-700' :
      status === 'finished' ? 'bg-green-100 text-green-700' :
      'bg-blue-100 text-blue-700'
    )}>
      {status}
    </span>
  )
}

function TBtn({ onClick, active, disabled, icon, title }: {
  onClick: () => void; active?: boolean; disabled?: boolean; icon: React.ReactNode; title: string
}) {
  return (
    <button onClick={onClick} disabled={disabled} title={title} className={cn(
      'p-1.5 rounded transition-colors flex items-center gap-0.5',
      active ? 'bg-bg-tertiary text-accent-primary' : 'text-text-secondary hover:bg-bg-secondary hover:text-text-primary',
      disabled && 'opacity-30 cursor-not-allowed'
    )}>
      {icon}
    </button>
  )
}

function Sep() {
  return <div className="w-px h-5 bg-border mx-1" />
}

/* ── Image insert ── */

function ImageInsertButton({ editor }: { editor: ReturnType<typeof useEditor> }) {
  const [open, setOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const popRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (popRef.current && !popRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const insertFromUrl = () => {
    const url = prompt('Image URL:')
    if (url?.trim()) editor?.chain().focus().setImage({ src: url.trim() }).run()
    setOpen(false)
  }

  const insertFromFile = () => { fileRef.current?.click(); setOpen(false) }

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post('/api/workspace/images', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      // Build full URL with token for authenticated access
      const token = localStorage.getItem('pagefly_token') || ''
      const src = `${api.defaults.baseURL || ''}${data.url}?token=${token}`
      editor?.chain().focus().setImage({ src }).run()
    } catch {
      alert('Image upload failed')
    }
    e.target.value = ''
  }

  return (
    <div className="relative" ref={popRef}>
      <button onClick={() => setOpen(!open)} title="Insert Image" className={cn(
        'p-1.5 rounded transition-colors text-text-secondary hover:bg-bg-secondary hover:text-text-primary',
        open && 'bg-bg-tertiary text-accent-primary'
      )}>
        <ImageIcon size={14} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-bg-primary border border-border rounded-lg shadow-lg z-[100] py-1 min-w-[150px]">
          <button onClick={insertFromUrl} className="flex items-center gap-2 w-full px-3 py-2 text-xs text-text-primary hover:bg-bg-secondary transition-colors">
            <Link size={12} /> From URL
          </button>
          <button onClick={insertFromFile} className="flex items-center gap-2 w-full px-3 py-2 text-xs text-text-primary hover:bg-bg-secondary transition-colors">
            <Upload size={12} /> Upload File
          </button>
        </div>
      )}
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFile} />
    </div>
  )
}

/* ── Table grid picker ── */

function TableInsertButton({ editor }: { editor: ReturnType<typeof useEditor> }) {
  const [open, setOpen] = useState(false)
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null)
  const [customRows, setCustomRows] = useState('')
  const [customCols, setCustomCols] = useState('')
  const popRef = useRef<HTMLDivElement>(null)
  const maxR = 8, maxC = 8

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (popRef.current && !popRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const insert = (rows: number, cols: number) => {
    if (rows < 1 || cols < 1) return
    editor?.chain().focus().insertTable({ rows, cols, withHeaderRow: true }).run()
    setOpen(false)
    setHover(null)
    setCustomRows('')
    setCustomCols('')
  }

  return (
    <div className="relative" ref={popRef}>
      <button onClick={() => setOpen(!open)} title="Insert Table" className={cn(
        'p-1.5 rounded transition-colors text-text-secondary hover:bg-bg-secondary hover:text-text-primary',
        open && 'bg-bg-tertiary text-accent-primary'
      )}>
        <TableIcon size={14} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-bg-primary border border-border rounded-lg shadow-lg z-[100] p-2">
          <div className="grid gap-[2px]" style={{ gridTemplateColumns: `repeat(${maxC}, 1fr)` }}>
            {Array.from({ length: maxR * maxC }, (_, i) => {
              const r = Math.floor(i / maxC) + 1
              const c = (i % maxC) + 1
              const active = hover && r <= hover.r && c <= hover.c
              return (
                <div key={i} onMouseEnter={() => setHover({ r, c })} onClick={() => insert(r, c)}
                  className={cn('w-[18px] h-[18px] rounded-[2px] border cursor-pointer transition-colors',
                    active ? 'bg-accent-primary/30 border-accent-primary' : 'bg-bg-secondary border-border hover:border-text-tertiary'
                  )} />
              )
            })}
          </div>
          <div className="text-center text-[10px] text-text-tertiary mt-1.5 font-mono">
            {hover ? `${hover.c} × ${hover.r}` : 'Select size'}
          </div>
          <div className="border-t border-border mt-2 pt-2">
            <div className="flex items-center gap-1.5">
              <input
                type="number" min={1} max={50} placeholder="cols" value={customCols}
                onChange={(e) => setCustomCols(e.target.value)}
                className="w-[48px] px-1.5 py-1 text-[11px] border border-border rounded bg-bg-secondary text-text-primary outline-none text-center"
              />
              <span className="text-[10px] text-text-tertiary">×</span>
              <input
                type="number" min={1} max={50} placeholder="rows" value={customRows}
                onChange={(e) => setCustomRows(e.target.value)}
                className="w-[48px] px-1.5 py-1 text-[11px] border border-border rounded bg-bg-secondary text-text-primary outline-none text-center"
              />
              <button
                onClick={() => insert(parseInt(customRows) || 3, parseInt(customCols) || 3)}
                className="px-2 py-1 text-[10px] font-semibold bg-accent-primary text-bg-primary rounded hover:bg-accent-secondary transition-colors"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
