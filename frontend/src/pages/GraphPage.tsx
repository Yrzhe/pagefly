import { useState, useEffect, useRef, useCallback } from 'react'
import { GitFork, Search, Maximize2, X, Expand, Pencil, Save } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '@/api/client'
import ForceGraph2D from 'react-force-graph-2d'

interface GraphNode {
  id: string
  label: string
  type: 'document' | 'wiki'
  category?: string
  subcategory?: string
  article_type?: string
  // d3 force fields
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}

interface GraphEdge {
  source: string
  target: string
  relation: string
}

interface GraphData {
  nodes: GraphNode[]
  links: GraphEdge[]
}

function rewriteImageUrls(markdown: string, node: GraphNode): string {
  const token = localStorage.getItem('pagefly_token') || ''
  const apiBase = import.meta.env.VITE_API_URL || ''
  return markdown.replace(
    /!\[([^\]]*)\]\((?!https?:\/\/)([^)]+)\)/g,
    (_, alt, path) => {
      const cleanPath = path.replace(/^\.\//, '')
      const endpoint = node.type === 'wiki' ? 'wiki' : 'documents'
      return `![${alt}](${apiBase}/api/${endpoint}/${node.id}/files/${cleanPath}?token=${token})`
    }
  )
}

const NODE_COLORS: Record<string, string> = {
  document: '#F59E0B',
  concept: '#2563EB',
  summary: '#D97706',
  connection: '#7C3AED',
  insight: '#16A34A',
  qa: '#EA580C',
  lint: '#DC2626',
  review: '#78716C',
}

function getNodeColor(node: GraphNode): string {
  if (node.type === 'wiki') return NODE_COLORS[node.article_type || ''] || '#2563EB'
  return NODE_COLORS.document
}

export function GraphPage() {
  const graphRef = useRef<any>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] })
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  const [panelContent, setPanelContent] = useState('')
  const [editContent, setEditContent] = useState('')
  const [panelMode, setPanelMode] = useState<'preview' | 'edit'>('preview')
  const [panelSaving, setPanelSaving] = useState(false)
  const [search, setSearch] = useState('')
  const [highlightNodes, setHighlightNodes] = useState<Set<string>>(new Set())
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })

  // Track container size
  useEffect(() => {
    const updateSize = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      }
    }
    updateSize()
    window.addEventListener('resize', updateSize)
    return () => window.removeEventListener('resize', updateSize)
  }, [])

  // Fetch graph data
  useEffect(() => {
    const fetchData = async () => {
      try {
        const { data } = await api.get('/api/graph')
        const nodes: GraphNode[] = data.nodes || []
        const edges: GraphEdge[] = data.edges || []
        const nodeSet = new Set(nodes.map(n => n.id))
        const validEdges = edges.filter(e => nodeSet.has(e.source) && nodeSet.has(e.target))
        setGraphData({ nodes, links: validEdges })
      } catch { /* silent */ }
    }
    fetchData()
  }, [])

  // Search highlight
  useEffect(() => {
    if (!search) {
      setHighlightNodes(new Set())
      return
    }
    const lower = search.toLowerCase()
    const matches = new Set(
      graphData.nodes
        .filter(n =>
          n.label.toLowerCase().includes(lower) ||
          (n.category || '').toLowerCase().includes(lower) ||
          (n.article_type || '').toLowerCase().includes(lower)
        )
        .map(n => n.id)
    )
    setHighlightNodes(matches)
  }, [search, graphData.nodes])

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node)
    // Center on clicked node
    graphRef.current?.centerAt(node.x, node.y, 500)
    graphRef.current?.zoom(2, 500)
  }, [])

  const openPanel = useCallback(async (node: GraphNode) => {
    setPanelOpen(true)
    setPanelMode('preview')
    setPanelContent('Loading...')
    try {
      if (node.type === 'wiki') {
        const { data } = await api.get(`/api/wiki/${node.id}`)
        setPanelContent(data.content || '')
        setEditContent(data.content || '')
      } else {
        const { data } = await api.get(`/api/documents/${node.id}`)
        setPanelContent(data.content || '')
        setEditContent(data.content || '')
      }
    } catch {
      setPanelContent('Failed to load content.')
    }
  }, [])

  const handlePanelSave = useCallback(async () => {
    if (!selectedNode) return
    setPanelSaving(true)
    try {
      if (selectedNode.type === 'document') {
        await api.put(`/api/documents/${selectedNode.id}/content`, { content: editContent })
      }
      setPanelContent(editContent)
      setPanelMode('preview')
    } catch { /* silent */ }
    finally { setPanelSaving(false) }
  }, [selectedNode, editContent])

  const closePanel = () => {
    setPanelOpen(false)
    setSelectedNode(null)
    setHighlightNodes(new Set())
  }

  const handleFit = () => {
    graphRef.current?.zoomToFit(400, 50)
  }

  // Custom node rendering
  const paintNode = useCallback((node: GraphNode, ctx: CanvasRenderingContext2D) => {
    const size = node.type === 'wiki' ? 6 : 5
    const color = getNodeColor(node)
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id)
    const isSelected = selectedNode?.id === node.id

    ctx.globalAlpha = isHighlighted ? 1 : 0.15

    // Draw node
    if (node.type === 'wiki') {
      // Diamond shape for wiki
      ctx.save()
      ctx.translate(node.x!, node.y!)
      ctx.rotate(Math.PI / 4)
      ctx.fillStyle = color
      ctx.fillRect(-size / 1.4, -size / 1.4, size * 1.4, size * 1.4)
      ctx.restore()
    } else {
      // Circle for documents
      ctx.beginPath()
      ctx.arc(node.x!, node.y!, size, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()
    }

    // Selected border
    if (isSelected) {
      ctx.beginPath()
      ctx.arc(node.x!, node.y!, size + 2, 0, 2 * Math.PI)
      ctx.strokeStyle = '#1C1917'
      ctx.lineWidth = 1.5
      ctx.stroke()
    }

    // Label
    const label = node.label.length > 20 ? node.label.slice(0, 20) + '...' : node.label
    ctx.font = '3px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillStyle = '#1C1917'
    ctx.fillText(label, node.x!, node.y! + size + 5)

    ctx.globalAlpha = 1
  }, [highlightNodes, selectedNode])

  return (
    <div className="flex flex-col h-screen">
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <GitFork size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Knowledge Graph</h1>
          <span className="text-xs text-text-tertiary">{graphData.nodes.length} nodes · {graphData.links.length} edges</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-2 border border-border rounded-[6px] w-56">
            <Search size={14} className="text-text-tertiary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search nodes..."
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none"
            />
          </div>
          <button onClick={handleFit} title="Center graph" className="p-2 border border-border rounded-[6px] hover:bg-bg-secondary transition-colors">
            <Maximize2 size={14} className="text-text-secondary" />
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden relative">
        <div ref={containerRef} className="flex-1 bg-bg-primary">
          {graphData.nodes.length > 0 && (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData as any}
              width={dimensions.width}
              height={dimensions.height}
              nodeCanvasObject={paintNode as any}
              nodePointerAreaPaint={((node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
                const size = 8
                ctx.fillStyle = color
                ctx.beginPath()
                ctx.arc(node.x!, node.y!, size, 0, 2 * Math.PI)
                ctx.fill()
              }) as any}
              onNodeClick={handleNodeClick as any}
              linkColor={() => '#D6D3D1'}
              linkWidth={1}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.3}
              cooldownTicks={200}
              enableNodeDrag={true}
              enableZoomInteraction={true}
              enablePanInteraction={true}
            />
          )}
        </div>

        {/* Legend */}
        <div className="absolute bottom-4 left-4 bg-bg-secondary/90 backdrop-blur-sm border border-border rounded-[8px] px-3 py-2 flex gap-4 text-[10px]">
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-[#F59E0B]" /> Document</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-[#2563EB] rotate-45" /> Concept</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-[#D97706] rotate-45" /> Summary</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-[#7C3AED] rotate-45" /> Connection</span>
        </div>

        {/* Node info tooltip */}
        {selectedNode && !panelOpen && (
          <aside className="absolute top-4 right-4 w-[240px] bg-bg-secondary/95 backdrop-blur-sm border border-border rounded-[12px] p-4 shadow-lg">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <span className="text-[10px] font-bold uppercase tracking-[1px] text-accent-primary">
                  {selectedNode.type === 'wiki' ? selectedNode.article_type : 'Document'}
                </span>
                <h3 className="text-xs font-semibold text-text-primary mt-0.5 leading-snug">{selectedNode.label}</h3>
              </div>
              <button onClick={() => { setSelectedNode(null); setHighlightNodes(new Set()) }} className="p-1 hover:bg-bg-tertiary rounded">
                <X size={11} className="text-text-tertiary" />
              </button>
            </div>
            <div className="flex flex-col gap-1 text-[10px] mb-3">
              <div className="flex justify-between">
                <span className="text-text-tertiary">ID</span>
                <span className="font-mono text-text-secondary">{selectedNode.id.slice(0, 10)}</span>
              </div>
              {selectedNode.category && (
                <div className="flex justify-between">
                  <span className="text-text-tertiary">Category</span>
                  <span className="text-text-secondary">{selectedNode.category}</span>
                </div>
              )}
            </div>
            <button
              onClick={() => openPanel(selectedNode)}
              className="w-full flex items-center justify-center gap-1.5 py-2 bg-accent-primary rounded-[6px] text-[11px] font-semibold text-bg-primary hover:bg-accent-secondary transition-colors"
            >
              <Expand size={12} /> Open Document
            </button>
          </aside>
        )}

        {/* Full content panel */}
        {panelOpen && selectedNode && (
          <aside className="absolute top-0 right-0 h-full w-[480px] bg-bg-primary border-l border-border shadow-lg flex flex-col z-10">
            <div className="flex items-center justify-between px-5 py-3 border-b border-border flex-shrink-0">
              <div className="flex-1 min-w-0">
                <span className="text-[9px] font-bold uppercase tracking-[1px] text-accent-primary">
                  {selectedNode.type === 'wiki' ? selectedNode.article_type : 'Document'}
                </span>
                <h3 className="text-sm font-semibold text-text-primary truncate">{selectedNode.label}</h3>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                {selectedNode.type === 'document' && (
                  panelMode === 'edit' ? (
                    <button onClick={handlePanelSave} disabled={panelSaving} className="flex items-center gap-1 px-2.5 py-1.5 bg-accent-primary rounded-[6px] text-[10px] font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60">
                      <Save size={10} /> {panelSaving ? '...' : 'Save'}
                    </button>
                  ) : (
                    <button onClick={() => { setEditContent(panelContent); setPanelMode('edit') }} className="flex items-center gap-1 px-2.5 py-1.5 border border-border rounded-[6px] text-[10px] text-text-secondary hover:bg-bg-secondary transition-colors">
                      <Pencil size={10} /> Edit
                    </button>
                  )
                )}
                <button onClick={closePanel} className="p-1.5 hover:bg-bg-secondary rounded transition-colors">
                  <X size={14} className="text-text-tertiary" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {panelMode === 'edit' ? (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full h-full p-5 bg-bg-primary text-text-primary text-sm font-mono leading-relaxed outline-none resize-none"
                  spellCheck={false}
                />
              ) : (
                <article className="px-5 py-4 prose-pagefly">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {rewriteImageUrls(panelContent, selectedNode)}
                  </ReactMarkdown>
                </article>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}
