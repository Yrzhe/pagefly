import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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
  ArrowLeft,
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
  Trash2,
  Plus,
} from 'lucide-react'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface WsDoc {
  id: string
  title: string
  content: string
  revision: number
  status: string
  created_by: string
  created_at: string
  updated_at: string
}

export function WorkspaceEditorPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [doc, setDoc] = useState<WsDoc | null>(null)
  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [lastSaved, setLastSaved] = useState('')

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

  useEffect(() => {
    if (!id) return
    ;(async () => {
      try {
        const { data } = await api.get(`/api/workspace/documents/${id}`)
        setDoc(data)
        setTitle(data.title)
        editor?.commands.setContent(data.content || '<p></p>')
        setLastSaved(data.updated_at)
      } catch {
        setError('Document not found')
      }
    })()
  }, [id, editor])

  const handleSave = useCallback(async () => {
    if (!doc || !editor) return
    setSaving(true)
    setError('')
    try {
      const html = editor.getHTML()
      const { data } = await api.patch(`/api/workspace/documents/${doc.id}`, {
        title,
        content: html,
        revision: doc.revision,
      })
      setDoc((prev) => prev ? { ...prev, revision: data.revision, title, content: html } : prev)
      setLastSaved(new Date().toISOString())
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [doc, editor, title])

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

  if (error && !doc) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-4">
        <p className="text-sm text-error">{error}</p>
        <button onClick={() => navigate('/workspace')} className="text-xs text-accent-primary hover:underline">
          Back to Workspace
        </button>
      </div>
    )
  }

  const charCount = editor?.storage.characterCount?.characters() ?? 0
  const wordCount = editor?.storage.characterCount?.words() ?? 0
  const isInTable = editor?.isActive('table') ?? false

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-4 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/workspace')} className="p-1.5 rounded hover:bg-bg-secondary text-text-tertiary">
            <ArrowLeft size={16} />
          </button>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Untitled"
            className="text-[15px] font-heading font-bold text-text-primary bg-transparent outline-none border-none w-[300px]"
          />
          <span className={cn(
            'text-[10px] px-2 py-0.5 rounded-full font-medium',
            doc?.status === 'draft' ? 'bg-amber-100 text-amber-700' :
            doc?.status === 'review' ? 'bg-blue-100 text-blue-700' :
            'bg-green-100 text-green-700'
          )}>
            {doc?.status || 'draft'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {error && <span className="text-[10px] text-error">{error}</span>}
          {lastSaved && (
            <span className="text-[10px] text-text-tertiary">
              rev {doc?.revision} · {charCount} chars · {wordCount} words
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 bg-accent-primary rounded-[8px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60"
          >
            <Save size={13} />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </header>

      {/* Toolbar */}
      {editor && (
        <div className="flex items-center gap-0.5 px-4 py-1.5 border-b border-border flex-shrink-0 overflow-x-auto">
          {/* Headings */}
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
            active={editor.isActive('heading', { level: 1 })}
            icon={<Heading1 size={15} />}
            title="Heading 1"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            active={editor.isActive('heading', { level: 2 })}
            icon={<Heading2 size={15} />}
            title="Heading 2"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
            active={editor.isActive('heading', { level: 3 })}
            icon={<Heading3 size={15} />}
            title="Heading 3"
          />
          <Divider />

          {/* Inline formatting */}
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleBold().run()}
            active={editor.isActive('bold')}
            icon={<Bold size={15} />}
            title="Bold (Ctrl+B)"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleItalic().run()}
            active={editor.isActive('italic')}
            icon={<Italic size={15} />}
            title="Italic (Ctrl+I)"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleStrike().run()}
            active={editor.isActive('strike')}
            icon={<Strikethrough size={15} />}
            title="Strikethrough"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleCode().run()}
            active={editor.isActive('code')}
            icon={<Code size={15} />}
            title="Inline Code"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleCodeBlock().run()}
            active={editor.isActive('codeBlock')}
            icon={<CodeSquare size={15} />}
            title="Code Block"
          />
          <Divider />

          {/* Block formatting */}
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            active={editor.isActive('bulletList')}
            icon={<List size={15} />}
            title="Bullet List"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            active={editor.isActive('orderedList')}
            icon={<ListOrdered size={15} />}
            title="Ordered List"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().toggleBlockquote().run()}
            active={editor.isActive('blockquote')}
            icon={<Quote size={15} />}
            title="Blockquote"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().setHorizontalRule().run()}
            icon={<Minus size={15} />}
            title="Horizontal Rule"
          />
          <Divider />

          {/* Insert: Image + Table */}
          <ImageInsertButton editor={editor} />
          <TableInsertButton editor={editor} />
          <Divider />

          {/* Table context actions */}
          {isInTable && (
            <>
              <ToolbarButton
                onClick={() => editor.chain().focus().addRowAfter().run()}
                icon={<><RowsIcon size={13} /><Plus size={9} /></>}
                title="Add Row"
              />
              <ToolbarButton
                onClick={() => editor.chain().focus().addColumnAfter().run()}
                icon={<><ColumnsIcon size={13} /><Plus size={9} /></>}
                title="Add Column"
              />
              <ToolbarButton
                onClick={() => editor.chain().focus().deleteRow().run()}
                icon={<><RowsIcon size={13} /><Minus size={9} /></>}
                title="Delete Row"
              />
              <ToolbarButton
                onClick={() => editor.chain().focus().deleteColumn().run()}
                icon={<><ColumnsIcon size={13} /><Minus size={9} /></>}
                title="Delete Column"
              />
              <ToolbarButton
                onClick={() => editor.chain().focus().deleteTable().run()}
                icon={<Trash2 size={13} />}
                title="Delete Table"
              />
              <Divider />
            </>
          )}

          {/* Undo/Redo */}
          <ToolbarButton
            onClick={() => editor.chain().focus().undo().run()}
            disabled={!editor.can().undo()}
            icon={<Undo2 size={15} />}
            title="Undo"
          />
          <ToolbarButton
            onClick={() => editor.chain().focus().redo().run()}
            disabled={!editor.can().redo()}
            icon={<Redo2 size={15} />}
            title="Redo"
          />
        </div>
      )}

      {/* Editor area */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[780px] mx-auto">
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  )
}

/* ── Toolbar components ── */

function ToolbarButton({
  onClick,
  active,
  disabled,
  icon,
  title,
}: {
  onClick: () => void
  active?: boolean
  disabled?: boolean
  icon: React.ReactNode
  title: string
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        'p-1.5 rounded transition-colors flex items-center gap-0.5',
        active ? 'bg-bg-tertiary text-accent-primary' : 'text-text-secondary hover:bg-bg-secondary hover:text-text-primary',
        disabled && 'opacity-30 cursor-not-allowed'
      )}
    >
      {icon}
    </button>
  )
}

function Divider() {
  return <div className="w-px h-5 bg-border mx-1" />
}

/* ── Image insert button with dropdown ── */

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
    if (url?.trim()) {
      editor?.chain().focus().setImage({ src: url.trim() }).run()
    }
    setOpen(false)
  }

  const insertFromFile = () => {
    fileRef.current?.click()
    setOpen(false)
  }

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        editor?.chain().focus().setImage({ src: reader.result }).run()
      }
    }
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  return (
    <div className="relative" ref={popRef}>
      <button
        onClick={() => setOpen(!open)}
        title="Insert Image"
        className={cn(
          'p-1.5 rounded transition-colors text-text-secondary hover:bg-bg-secondary hover:text-text-primary',
          open && 'bg-bg-tertiary text-accent-primary'
        )}
      >
        <ImageIcon size={15} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-bg-primary border border-border rounded-lg shadow-md z-50 py-1 min-w-[160px]">
          <button
            onClick={insertFromUrl}
            className="flex items-center gap-2 w-full px-3 py-2 text-xs text-text-primary hover:bg-bg-secondary transition-colors"
          >
            <Link size={13} /> From URL
          </button>
          <button
            onClick={insertFromFile}
            className="flex items-center gap-2 w-full px-3 py-2 text-xs text-text-primary hover:bg-bg-secondary transition-colors"
          >
            <Upload size={13} /> Upload File
          </button>
        </div>
      )}
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFile} />
    </div>
  )
}

/* ── Table insert button with grid picker ── */

function TableInsertButton({ editor }: { editor: ReturnType<typeof useEditor> }) {
  const [open, setOpen] = useState(false)
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null)
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
    editor?.chain().focus().insertTable({ rows, cols, withHeaderRow: true }).run()
    setOpen(false)
    setHover(null)
  }

  return (
    <div className="relative" ref={popRef}>
      <button
        onClick={() => setOpen(!open)}
        title="Insert Table"
        className={cn(
          'p-1.5 rounded transition-colors text-text-secondary hover:bg-bg-secondary hover:text-text-primary',
          open && 'bg-bg-tertiary text-accent-primary'
        )}
      >
        <TableIcon size={15} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-bg-primary border border-border rounded-lg shadow-md z-50 p-2">
          <div
            className="grid gap-[2px]"
            style={{ gridTemplateColumns: `repeat(${maxC}, 1fr)` }}
          >
            {Array.from({ length: maxR * maxC }, (_, i) => {
              const r = Math.floor(i / maxC) + 1
              const c = (i % maxC) + 1
              const active = hover && r <= hover.r && c <= hover.c
              return (
                <div
                  key={i}
                  onMouseEnter={() => setHover({ r, c })}
                  onClick={() => insert(r, c)}
                  className={cn(
                    'w-[18px] h-[18px] rounded-[2px] border cursor-pointer transition-colors',
                    active ? 'bg-accent-primary/30 border-accent-primary' : 'bg-bg-secondary border-border hover:border-text-tertiary'
                  )}
                />
              )
            })}
          </div>
          <div className="text-center text-[10px] text-text-tertiary mt-1.5 font-mono">
            {hover ? `${hover.c} × ${hover.r}` : 'Select size'}
          </div>
        </div>
      )}
    </div>
  )
}
