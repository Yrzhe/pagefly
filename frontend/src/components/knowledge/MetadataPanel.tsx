interface Document {
  id: string
  title: string
  description: string
  category: string
  subcategory: string
  tags: string
  status: string
  relevance_score: number
  temporal_type: string
  source_type: string
  ingested_at: string
  classified_at: string
  original_filename: string
}

interface Props {
  doc: Document | null
  onUpdate: () => void
}

function parseTags(raw: string): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map(String)
  } catch { /* not JSON */ }
  return raw.split(',').map((t) => t.trim()).filter(Boolean)
}

export function MetadataPanel({ doc }: Props) {
  if (!doc) {
    return (
      <aside className="w-[280px] flex-shrink-0 flex items-center justify-center text-text-tertiary text-xs p-4">
        No document selected
      </aside>
    )
  }

  const tags = parseTags(doc.tags)
  const relevance = doc.relevance_score || 0
  const categoryPath = [doc.category, doc.subcategory].filter(Boolean).join(' / ')

  return (
    <aside className="w-[280px] flex-shrink-0 overflow-y-auto p-4 flex flex-col gap-4">
      {/* Document info */}
      <div className="flex flex-col gap-3">
        <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">
          Document Info
        </span>

        <InfoRow label="Title" value={doc.title || 'Untitled'} />

        {doc.description && (
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-text-tertiary">Description</span>
            <p className="text-xs text-text-secondary leading-relaxed">{doc.description}</p>
          </div>
        )}

        {tags.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] text-text-tertiary">Tags</span>
            <div className="flex flex-wrap gap-1.5">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-0.5 bg-bg-tertiary rounded-full text-[11px] text-accent-secondary"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        <InfoRow label="Category" value={categoryPath || '—'} />

        {relevance > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-text-tertiary">Relevance</span>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent-primary rounded-full"
                  style={{ width: `${relevance * 10}%` }}
                />
              </div>
              <span className="font-mono text-[11px] text-text-primary">{relevance}/10</span>
            </div>
          </div>
        )}

        {doc.temporal_type && (
          <InfoRow label="Temporal" value={doc.temporal_type} />
        )}
      </div>

      <div className="h-px bg-border" />

      {/* System metadata */}
      <div className="flex flex-col gap-2.5">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[1.5px] text-text-tertiary">
          System
        </span>

        <MetaRow label="ID" value={doc.id.slice(0, 12)} mono />
        <MetaRow label="Ingested" value={doc.ingested_at?.split('T')[0] || '—'} mono />
        <MetaRow label="Classified" value={doc.classified_at?.split('T')[0] || '—'} mono />
        <MetaRow label="Source" value={doc.source_type || '—'} mono />
        <MetaRow label="Status" value={doc.status || '—'} />
        <MetaRow label="File" value={doc.original_filename || '—'} />
      </div>
    </aside>
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
      <span className={`text-[11px] text-text-secondary truncate ml-2 ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}
