import { useState, useEffect, useRef, useCallback } from 'react'
import { GitFork, Search, ZoomIn, ZoomOut, Maximize2, X, Expand, Pencil, Save } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import cytoscape from 'cytoscape'
import api from '@/api/client'

interface GraphNode {
  id: string
  label: string
  type: 'document' | 'wiki'
  category?: string
  subcategory?: string
  article_type?: string
}

interface GraphEdge {
  source: string
  target: string
  relation: string
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
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  const [panelContent, setPanelContent] = useState('')
  const [editContent, setEditContent] = useState('')
  const [panelMode, setPanelMode] = useState<'preview' | 'edit'>('preview')
  const [panelSaving, setPanelSaving] = useState(false)
  const [search, setSearch] = useState('')
  const [stats, setStats] = useState({ nodes: 0, edges: 0 })

  const initGraph = useCallback(async () => {
    if (!containerRef.current) return

    try {
      const { data } = await api.get('/api/graph')
      const nodes: GraphNode[] = data.nodes || []
      const edges: GraphEdge[] = data.edges || []

      setStats({ nodes: nodes.length, edges: edges.length })

      // Build cytoscape elements
      const nodeSet = new Set(nodes.map((n) => n.id))
      const cyNodes = nodes.map((n) => ({
        data: {
          id: n.id,
          label: n.label.length > 20 ? n.label.slice(0, 20) + '...' : n.label,
          fullLabel: n.label,
          type: n.type,
          category: n.category || '',
          subcategory: n.subcategory || '',
          article_type: n.article_type || '',
          color: getNodeColor(n),
          size: n.type === 'wiki' ? 40 : 30,
        },
      }))

      const cyEdges = edges
        .filter((e) => nodeSet.has(e.source) && nodeSet.has(e.target))
        .map((e, i) => ({
          data: {
            id: `e${i}`,
            source: e.source,
            target: e.target,
            relation: e.relation,
          },
        }))

      const cy = cytoscape({
        container: containerRef.current,
        elements: [...cyNodes, ...cyEdges],
        style: [
          {
            selector: 'node',
            style: {
              'background-color': 'data(color)',
              label: 'data(label)',
              'font-size': '10px',
              'font-family': 'system-ui, sans-serif',
              color: '#1C1917',
              'text-valign': 'bottom',
              'text-margin-y': 6,
              width: 'data(size)',
              height: 'data(size)',
              'border-width': 2,
              'border-color': '#E7E5E4',
            },
          },
          {
            selector: 'node[type="wiki"]',
            style: {
              shape: 'diamond',
            },
          },
          {
            selector: 'node:selected',
            style: {
              'border-width': 3,
              'border-color': '#1C1917',
              'background-opacity': 1,
            },
          },
          {
            selector: 'node.highlighted',
            style: {
              'border-width': 3,
              'border-color': '#F59E0B',
              'background-opacity': 1,
            },
          },
          {
            selector: 'node.dimmed',
            style: {
              opacity: 0.2,
            },
          },
          {
            selector: 'edge',
            style: {
              width: 1.5,
              'line-color': '#E7E5E4',
              'target-arrow-color': '#A8A29E',
              'target-arrow-shape': 'triangle',
              'curve-style': 'bezier',
              'arrow-scale': 0.8,
            },
          },
          {
            selector: 'edge.highlighted',
            style: {
              'line-color': '#F59E0B',
              'target-arrow-color': '#F59E0B',
              width: 2.5,
            },
          },
          {
            selector: 'edge.dimmed',
            style: {
              opacity: 0.1,
            },
          },
        ],
        // Use cose layout for circular shape, then allow manual dragging
        layout: {
          name: 'cose',
          animate: true,
          animationDuration: 800,
          fit: true,
          padding: 60,
          nodeDimensionsIncludeLabels: true,
          nodeRepulsion: () => 8000,
          idealEdgeLength: () => 120,
          edgeElasticity: () => 100,
          gravity: 1,
          numIter: 500,
          randomize: false,
        } as cytoscape.LayoutOptions,
        // Interaction
        userZoomingEnabled: true,
        userPanningEnabled: true,
        boxSelectionEnabled: false,
        minZoom: 0.1,
        maxZoom: 5,
        wheelSensitivity: 0.3,
      })

      cy.on('tap', 'node', (e) => {
        const node = e.target
        const nodeData: GraphNode = {
          id: node.data('id'),
          label: node.data('fullLabel'),
          type: node.data('type'),
          category: node.data('category'),
          subcategory: node.data('subcategory'),
          article_type: node.data('article_type'),
        }
        setSelectedNode(nodeData)

        // Highlight connected nodes
        cy.elements().removeClass('highlighted dimmed')
        const connected = node.neighborhood()
        cy.elements().addClass('dimmed')
        node.removeClass('dimmed').addClass('highlighted')
        connected.removeClass('dimmed').addClass('highlighted')
      })

      cy.on('tap', (e) => {
        if (e.target === cy) {
          setSelectedNode(null)
          cy.elements().removeClass('highlighted dimmed')
        }
      })

      cyRef.current = cy
    } catch {
      // silent
    }
  }, [])

  useEffect(() => {
    initGraph()
    return () => { cyRef.current?.destroy() }
  }, [initGraph])

  // Search highlight
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('highlighted dimmed')
    if (!search) return
    const lower = search.toLowerCase()
    const matches = cy.nodes().filter((n) =>
      n.data('fullLabel').toLowerCase().includes(lower) ||
      n.data('category').toLowerCase().includes(lower) ||
      n.data('article_type').toLowerCase().includes(lower)
    )
    if (matches.length > 0) {
      cy.elements().addClass('dimmed')
      matches.forEach((n) => {
        n.removeClass('dimmed').addClass('highlighted')
        n.neighborhood().removeClass('dimmed').addClass('highlighted')
      })
    }
  }, [search])

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
    cyRef.current?.elements().removeClass('highlighted dimmed')
  }

  const handleZoomIn = () => {
    const cy = cyRef.current
    if (!cy) return
    cy.animate({ zoom: { level: cy.zoom() * 1.3, position: cy.extent() ? { x: (cy.extent().x1 + cy.extent().x2) / 2, y: (cy.extent().y1 + cy.extent().y2) / 2 } : { x: 0, y: 0 } }, duration: 200 })
  }
  const handleZoomOut = () => {
    const cy = cyRef.current
    if (!cy) return
    cy.animate({ zoom: { level: cy.zoom() / 1.3, position: cy.extent() ? { x: (cy.extent().x1 + cy.extent().x2) / 2, y: (cy.extent().y1 + cy.extent().y2) / 2 } : { x: 0, y: 0 } }, duration: 200 })
  }
  const handleFit = () => {
    const cy = cyRef.current
    if (!cy) return
    cy.animate({ fit: { eles: cy.elements(), padding: 50 }, duration: 400 })
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
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search nodes..."
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none"
            />
          </div>
          <div className="flex gap-1">
            <button onClick={handleZoomIn} className="p-2 border border-border rounded-[6px] hover:bg-bg-secondary transition-colors"><ZoomIn size={14} className="text-text-secondary" /></button>
            <button onClick={handleZoomOut} className="p-2 border border-border rounded-[6px] hover:bg-bg-secondary transition-colors"><ZoomOut size={14} className="text-text-secondary" /></button>
            <button onClick={handleFit} title="Center graph" className="p-2 border border-border rounded-[6px] hover:bg-bg-secondary transition-colors"><Maximize2 size={14} className="text-text-secondary" /></button>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden relative">
        {/* Graph canvas */}
        <div ref={containerRef} className="flex-1 bg-bg-primary" />

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
              <button onClick={() => { setSelectedNode(null); cyRef.current?.elements().removeClass('highlighted dimmed') }} className="p-1 hover:bg-bg-tertiary rounded">
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
