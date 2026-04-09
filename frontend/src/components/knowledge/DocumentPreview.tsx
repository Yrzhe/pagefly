import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '@/api/client'

interface Document {
  id: string
  title: string
  category: string
  subcategory: string
  source_type: string
  ingested_at: string
}

interface Props {
  doc: Document | null
  content: string
}

function rewriteImageUrls(markdown: string, docId: string): string {
  const token = localStorage.getItem('pagefly_token') || ''
  return markdown.replace(
    /!\[([^\]]*)\]\((?!https?:\/\/)([^)]+)\)/g,
    (_, alt, path) => `![${alt}](/api/documents/${docId}/files/${path}?token=${token})`
  )
}

export function DocumentPreview({ doc, content }: Props) {
  const [mode, setMode] = useState<'preview' | 'edit'>('preview')
  const [editContent, setEditContent] = useState('')
  const [displayContent, setDisplayContent] = useState(content)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setDisplayContent(content)
    setEditContent(content)
    setMode('preview')
  }, [content])

  const handleSave = useCallback(async () => {
    if (!doc || editContent === displayContent) {
      setMode('preview')
      return
    }
    setSaving(true)
    try {
      await api.put(`/api/documents/${doc.id}/content`, { content: editContent })
      setDisplayContent(editContent)
    } catch {
      // save failed, keep edit content for retry
    } finally {
      setSaving(false)
      setMode('preview')
    }
  }, [doc, editContent, displayContent])

  if (!doc) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-tertiary text-sm">
        Select a document from the tree to preview
      </div>
    )
  }

  const tags = [doc.category, doc.subcategory].filter(Boolean)
  const timeAgo = doc.ingested_at ? new Date(doc.ingested_at).toLocaleDateString() : ''
  const processedContent = rewriteImageUrls(displayContent, doc.id)

  return (
    <div className="flex-1 flex flex-col border-r border-border overflow-hidden">
      {/* Document header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border flex-shrink-0">
        <div className="flex flex-col gap-1.5">
          <h2 className="font-heading text-lg font-bold text-text-primary">{doc.title || 'Untitled'}</h2>
          <div className="flex items-center gap-2">
            {tags.map((tag) => (
              <span key={tag} className="px-2 py-0.5 bg-bg-tertiary rounded-full text-[10px] font-medium text-accent-secondary">
                {tag}
              </span>
            ))}
            {timeAgo && <span className="text-[10px] text-text-tertiary">{timeAgo}</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {saving && <span className="text-[10px] text-accent-primary">Saving...</span>}
          <div className="flex gap-1">
            <button
              onClick={() => { if (mode === 'edit') handleSave(); else setMode('preview'); }}
              className={`px-3.5 py-1.5 rounded-[6px] text-xs font-semibold transition-colors ${
                mode === 'preview'
                  ? 'bg-text-primary text-bg-primary'
                  : 'border border-border text-text-secondary hover:bg-bg-secondary'
              }`}
            >
              Preview
            </button>
            <button
              onClick={() => setMode('edit')}
              className={`px-3.5 py-1.5 rounded-[6px] text-xs font-semibold transition-colors ${
                mode === 'edit'
                  ? 'bg-text-primary text-bg-primary'
                  : 'border border-border text-text-secondary hover:bg-bg-secondary'
              }`}
            >
              Edit
            </button>
          </div>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto">
        {mode === 'preview' ? (
          <article className="px-8 py-6 prose-pagefly">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {processedContent}
            </ReactMarkdown>
          </article>
        ) : (
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="w-full h-full p-6 bg-bg-primary text-text-primary text-sm font-mono leading-relaxed outline-none resize-none"
            spellCheck={false}
          />
        )}
      </div>
    </div>
  )
}
