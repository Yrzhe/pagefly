import { useState, useEffect, useRef, useCallback } from 'react'
import { GitFork, Search, Maximize2, X, Expand, Pencil, Save } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, type SimulationNodeDatum, type SimulationLinkDatum } from 'd3-force'
import { select } from 'd3-selection'
import { zoom as d3Zoom, zoomIdentity } from 'd3-zoom'
// d3-drag replaced with native pointer events for node dragging
import api from '@/api/client'

interface GNode extends SimulationNodeDatum {
  id: string
  label: string
  type: 'document' | 'wiki'
  category: string
  subcategory: string
  article_type: string
}

interface GLink extends SimulationLinkDatum<GNode> {
  source: string | GNode
  target: string | GNode
}

const COLORS: Record<string, string> = {
  document: '#F59E0B', concept: '#2563EB', summary: '#D97706',
  connection: '#7C3AED', insight: '#16A34A', qa: '#EA580C',
  lint: '#DC2626', review: '#78716C',
}

function nodeColor(n: GNode): string {
  return n.type === 'wiki' ? (COLORS[n.article_type] || '#2563EB') : COLORS.document
}

function rewriteImageUrls(md: string, node: GNode): string {
  const token = localStorage.getItem('pagefly_token') || ''
  const base = import.meta.env.VITE_API_URL || ''
  return md.replace(/!\[([^\]]*)\]\((?!https?:\/\/)([^)]+)\)/g, (_, alt, path) => {
    const ep = node.type === 'wiki' ? 'wiki' : 'documents'
    return `![${alt}](${base}/api/${ep}/${node.id}/files/${path.replace(/^\.\//, '')}?token=${token})`
  })
}

export function GraphPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const simRef = useRef<ReturnType<typeof forceSimulation<GNode>> | null>(null)
  const nodesRef = useRef<GNode[]>([])
  const linksRef = useRef<GLink[]>([])
  const transformRef = useRef(zoomIdentity)

  const [selectedNode, setSelectedNode] = useState<GNode | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  const [panelContent, setPanelContent] = useState('')
  const [editContent, setEditContent] = useState('')
  const [panelMode, setPanelMode] = useState<'preview' | 'edit'>('preview')
  const [panelSaving, setPanelSaving] = useState(false)
  const [search, setSearch] = useState('')
  const [highlightIds, setHighlightIds] = useState<Set<string>>(new Set())
  const [stats, setStats] = useState({ nodes: 0, edges: 0 })

  // Use refs for draw function so it doesn't trigger useEffect re-init
  const selectedNodeRef = useRef<GNode | null>(null)
  const highlightIdsRef = useRef<Set<string>>(new Set())
  selectedNodeRef.current = selectedNode
  highlightIdsRef.current = highlightIds

  // Draw — reads from refs so it never causes useEffect re-init
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const t = transformRef.current
    const w = canvas.width
    const h = canvas.height
    const currentHighlight = highlightIdsRef.current
    const currentSelected = selectedNodeRef.current

    ctx.clearRect(0, 0, w, h)
    ctx.save()
    ctx.translate(t.x, t.y)
    ctx.scale(t.k, t.k)

    const hasHighlight = currentHighlight.size > 0

    // Edges
    for (const link of linksRef.current) {
      const s = link.source as GNode
      const tgt = link.target as GNode
      if (s.x == null || tgt.x == null) continue
      const dimmed = hasHighlight && !currentHighlight.has(s.id) && !currentHighlight.has(tgt.id)
      ctx.beginPath()
      ctx.moveTo(s.x, s.y!)
      ctx.lineTo(tgt.x, tgt.y!)
      ctx.strokeStyle = dimmed ? 'rgba(231,229,228,0.15)' : '#D6D3D1'
      ctx.lineWidth = dimmed ? 0.5 : 1
      ctx.stroke()
    }

    // Nodes
    for (const node of nodesRef.current) {
      if (node.x == null) continue
      const isSelected = currentSelected?.id === node.id
      const dimmed = hasHighlight && !currentHighlight.has(node.id)
      const r = node.type === 'wiki' ? 7 : 5
      const color = nodeColor(node)

      ctx.globalAlpha = dimmed ? 0.12 : 1

      if (node.type === 'wiki') {
        ctx.save()
        ctx.translate(node.x, node.y!)
        ctx.rotate(Math.PI / 4)
        ctx.fillStyle = color
        ctx.fillRect(-r * 0.7, -r * 0.7, r * 1.4, r * 1.4)
        ctx.restore()
      } else {
        ctx.beginPath()
        ctx.arc(node.x, node.y!, r, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.fill()
      }

      if (isSelected) {
        ctx.beginPath()
        ctx.arc(node.x, node.y!, r + 3, 0, Math.PI * 2)
        ctx.strokeStyle = '#1C1917'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      // Label
      ctx.font = '4px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillStyle = dimmed ? 'rgba(120,113,108,0.3)' : '#78716C'
      const label = node.label.length > 16 ? node.label.slice(0, 16) + '…' : node.label
      ctx.fillText(label, node.x, node.y! + r + 7)

      ctx.globalAlpha = 1
    }

    ctx.restore()
  }, []) // stable — reads from refs

  // Init
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const resize = () => {
      const parent = canvas.parentElement!
      canvas.width = parent.clientWidth
      canvas.height = parent.clientHeight
      draw()
    }
    resize()
    window.addEventListener('resize', resize)

    // Fetch data
    const init = async () => {
      try {
        const { data } = await api.get('/api/graph')
        const nodes: GNode[] = (data.nodes || []).map((n: any) => ({
          ...n, label: n.label, category: n.category || '', subcategory: n.subcategory || '', article_type: n.article_type || '',
        }))
        const nodeSet = new Set(nodes.map(n => n.id))
        const links: GLink[] = (data.edges || []).filter((e: any) => nodeSet.has(e.source) && nodeSet.has(e.target))
        setStats({ nodes: nodes.length, edges: links.length })
        nodesRef.current = nodes
        linksRef.current = links

        const sim = forceSimulation(nodes)
          .force('link', forceLink<GNode, GLink>(links).id(d => d.id).distance(80))
          .force('charge', forceManyBody().strength(-200))
          .force('center', forceCenter(canvas.width / 2, canvas.height / 2))
          .force('collide', forceCollide(20))
          .alphaDecay(0.02)
          .on('tick', draw)

        simRef.current = sim

        // Hit test
        const findNode = (px: number, py: number): GNode | undefined => {
          const t = transformRef.current
          const mx = (px - t.x) / t.k
          const my = (py - t.y) / t.k
          // Search in reverse for top-most node
          for (let i = nodes.length - 1; i >= 0; i--) {
            const n = nodes[i]
            const r = n.type === 'wiki' ? 12 : 10
            if (n.x != null && Math.hypot(n.x - mx, n.y! - my) < r) return n
          }
          return undefined
        }

        // Zoom (only when not on a node)
        let isDraggingNode = false
        const zoomBehavior = d3Zoom<HTMLCanvasElement, unknown>()
          .scaleExtent([0.1, 6])
          .filter((event) => {
            // Allow wheel zoom always, but block pan if dragging a node
            if (event.type === 'wheel') return true
            if (isDraggingNode) return false
            // Check if mouse is on a node — if so, don't start zoom pan
            const node = findNode(event.offsetX, event.offsetY)
            return !node
          })
          .on('zoom', (event) => {
            transformRef.current = event.transform
            draw()
          })
        select(canvas).call(zoomBehavior)

        // Drag nodes (only activate after mouse moves > 3px)
        let draggedNode: GNode | undefined
        let dragStartPos = { x: 0, y: 0 }
        let dragActivated = false

        canvas.addEventListener('pointerdown', (event) => {
          const node = findNode(event.offsetX, event.offsetY)
          if (!node) return
          draggedNode = node
          dragStartPos = { x: event.offsetX, y: event.offsetY }
          dragActivated = false
          canvas.setPointerCapture(event.pointerId)
        })
        canvas.addEventListener('pointermove', (event) => {
          if (!draggedNode) return
          // Only activate drag after threshold (avoids triggering on click)
          if (!dragActivated) {
            const dist = Math.hypot(event.offsetX - dragStartPos.x, event.offsetY - dragStartPos.y)
            if (dist < 3) return
            dragActivated = true
            isDraggingNode = true
            sim.alphaTarget(0.3).restart()
            draggedNode.fx = draggedNode.x
            draggedNode.fy = draggedNode.y
          }
          const t = transformRef.current
          draggedNode.fx = (event.offsetX - t.x) / t.k
          draggedNode.fy = (event.offsetY - t.y) / t.k
        })
        const endDrag = () => {
          if (draggedNode && dragActivated) {
            sim.alphaTarget(0)
            draggedNode.fx = null
            draggedNode.fy = null
          }
          draggedNode = undefined
          dragActivated = false
          isDraggingNode = false
        }
        canvas.addEventListener('pointerup', endDrag)
        canvas.addEventListener('pointercancel', endDrag)

        // Click
        canvas.addEventListener('click', (event) => {
          const node = findNode(event.offsetX, event.offsetY)
          if (node) {
            setSelectedNode(node)
          } else {
            setSelectedNode(null)
            setPanelOpen(false)
            setHighlightIds(new Set())
          }
        })

      } catch { /* silent */ }
    }
    init()

    return () => {
      window.removeEventListener('resize', resize)
      simRef.current?.stop()
    }
  }, [draw])

  // Redraw when selection/highlight changes (without re-init)
  useEffect(() => { draw() }, [selectedNode, highlightIds, draw])

  // Search highlight
  useEffect(() => {
    if (!search) { setHighlightIds(new Set()); return }
    const lower = search.toLowerCase()
    const ids = new Set(
      nodesRef.current
        .filter(n => n.label.toLowerCase().includes(lower) || n.category.toLowerCase().includes(lower) || n.article_type.toLowerCase().includes(lower))
        .map(n => n.id)
    )
    setHighlightIds(ids)
  }, [search])

  // Highlight selected + neighbors
  useEffect(() => {
    if (!selectedNode || search) return
    const ids = new Set([selectedNode.id])
    for (const link of linksRef.current) {
      const s = (link.source as GNode).id || link.source as string
      const t = (link.target as GNode).id || link.target as string
      if (s === selectedNode.id) ids.add(t)
      if (t === selectedNode.id) ids.add(s)
    }
    setHighlightIds(ids)
  }, [selectedNode, search])

  const openPanel = useCallback(async (node: GNode) => {
    setPanelOpen(true)
    setPanelMode('preview')
    setPanelContent('Loading...')
    try {
      const ep = node.type === 'wiki' ? `/api/wiki/${node.id}` : `/api/documents/${node.id}`
      const { data } = await api.get(ep)
      setPanelContent(data.content || '')
      setEditContent(data.content || '')
    } catch { setPanelContent('Failed to load.') }
  }, [])

  const handlePanelSave = useCallback(async () => {
    if (!selectedNode || selectedNode.type !== 'document') return
    setPanelSaving(true)
    try {
      await api.put(`/api/documents/${selectedNode.id}/content`, { content: editContent })
      setPanelContent(editContent)
      setPanelMode('preview')
    } catch { /* silent */ }
    finally { setPanelSaving(false) }
  }, [selectedNode, editContent])

  const closePanel = () => { setPanelOpen(false); setSelectedNode(null); setHighlightIds(new Set()) }

  const handleFit = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    transformRef.current = zoomIdentity
    simRef.current?.alpha(0.3).restart()
    draw()
  }

  return (
    <div className="flex flex-col h-screen">
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <GitFork size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Knowledge Graph</h1>
          <span className="text-xs text-text-tertiary">{stats.nodes} nodes · {stats.edges} edges</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-2 border border-border rounded-[6px] w-56">
            <Search size={14} className="text-text-tertiary" />
            <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search nodes..." className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none" />
          </div>
          <button onClick={handleFit} title="Center graph" className="p-2 border border-border rounded-[6px] hover:bg-bg-secondary transition-colors">
            <Maximize2 size={14} className="text-text-secondary" />
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden relative">
        <canvas ref={canvasRef} className="flex-1 bg-bg-primary cursor-grab active:cursor-grabbing" />

        {/* Legend */}
        <div className="absolute bottom-4 left-4 bg-bg-secondary/90 backdrop-blur-sm border border-border rounded-[8px] px-3 py-2 flex gap-4 text-[10px]">
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-[#F59E0B]" /> Document</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-[#2563EB] rotate-45" /> Concept</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-[#D97706] rotate-45" /> Summary</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-[#7C3AED] rotate-45" /> Connection</span>
        </div>

        {/* Node tooltip */}
        {selectedNode && !panelOpen && (
          <aside className="absolute top-4 right-4 w-[240px] bg-bg-secondary/95 backdrop-blur-sm border border-border rounded-[12px] p-4 shadow-lg">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <span className="text-[10px] font-bold uppercase tracking-[1px] text-accent-primary">{selectedNode.type === 'wiki' ? selectedNode.article_type : 'Document'}</span>
                <h3 className="text-xs font-semibold text-text-primary mt-0.5 leading-snug">{selectedNode.label}</h3>
              </div>
              <button onClick={() => { setSelectedNode(null); setHighlightIds(new Set()) }} className="p-1 hover:bg-bg-tertiary rounded"><X size={11} className="text-text-tertiary" /></button>
            </div>
            {selectedNode.category && <div className="flex justify-between text-[10px] mb-3"><span className="text-text-tertiary">Category</span><span className="text-text-secondary">{selectedNode.category}</span></div>}
            <button onClick={() => openPanel(selectedNode)} className="w-full flex items-center justify-center gap-1.5 py-2 bg-accent-primary rounded-[6px] text-[11px] font-semibold text-bg-primary hover:bg-accent-secondary transition-colors">
              <Expand size={12} /> Open Document
            </button>
          </aside>
        )}

        {/* Content panel */}
        {panelOpen && selectedNode && (
          <aside className="absolute top-0 right-0 h-full w-[480px] bg-bg-primary border-l border-border shadow-lg flex flex-col z-10">
            <div className="flex items-center justify-between px-5 py-3 border-b border-border flex-shrink-0">
              <div className="flex-1 min-w-0">
                <span className="text-[9px] font-bold uppercase tracking-[1px] text-accent-primary">{selectedNode.type === 'wiki' ? selectedNode.article_type : 'Document'}</span>
                <h3 className="text-sm font-semibold text-text-primary truncate">{selectedNode.label}</h3>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                {selectedNode.type === 'document' && (
                  panelMode === 'edit' ? (
                    <button onClick={handlePanelSave} disabled={panelSaving} className="flex items-center gap-1 px-2.5 py-1.5 bg-accent-primary rounded-[6px] text-[10px] font-semibold text-bg-primary"><Save size={10} /> {panelSaving ? '...' : 'Save'}</button>
                  ) : (
                    <button onClick={() => { setEditContent(panelContent); setPanelMode('edit') }} className="flex items-center gap-1 px-2.5 py-1.5 border border-border rounded-[6px] text-[10px] text-text-secondary"><Pencil size={10} /> Edit</button>
                  )
                )}
                <button onClick={closePanel} className="p-1.5 hover:bg-bg-secondary rounded"><X size={14} className="text-text-tertiary" /></button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {panelMode === 'edit' ? (
                <textarea value={editContent} onChange={(e) => setEditContent(e.target.value)} className="w-full h-full p-5 bg-bg-primary text-text-primary text-sm font-mono leading-relaxed outline-none resize-none" spellCheck={false} />
              ) : (
                <article className="px-5 py-4 prose-pagefly">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{rewriteImageUrls(panelContent, selectedNode)}</ReactMarkdown>
                </article>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}
