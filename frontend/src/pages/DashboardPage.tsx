import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { LayoutDashboard, FileText, BookOpen, Clock, FolderOpen, Calendar, ArrowRight, Bot } from 'lucide-react'
import api from '@/api/client'
import { cn } from '@/lib/utils'
import { OnboardingWizard } from '@/components/OnboardingWizard'

const ONBOARDING_DISMISSED_KEY = 'pagefly_onboarding_dismissed'

interface Stats {
  documents: number
  wiki_articles: number
  operations: number
  scheduled_tasks: number
  categories: Record<string, number>
}

interface Activity {
  id: number
  document_id: string
  operation: string
  to_path: string
  created_at: string
  doc_title: string | null
}

interface TrendDay {
  date: string
  ingest: number
  classify: number
  wiki_compile: number
  total: number
}

const OP_LABELS: Record<string, { label: string; color: string }> = {
  ingest: { label: 'Ingested', color: 'text-blue-600 bg-blue-50' },
  classify: { label: 'Classified', color: 'text-purple-600 bg-purple-50' },
  move: { label: 'Moved', color: 'text-amber-600 bg-amber-50' },
  delete: { label: 'Deleted', color: 'text-red-600 bg-red-50' },
  wiki_compile: { label: 'Wiki', color: 'text-green-600 bg-green-50' },
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [activity, setActivity] = useState<Activity[]>([])
  const [trends, setTrends] = useState<TrendDay[]>([])
  const [loading, setLoading] = useState(true)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const navigate = useNavigate()

  const fetchData = useCallback(async () => {
    try {
      const [s, a, t] = await Promise.all([
        api.get('/api/stats'),
        api.get('/api/activity?limit=15'),
        api.get('/api/trends?days=14'),
      ])
      setStats(s.data)
      setActivity(a.data.activity || [])
      setTrends(t.data.trends || [])
    } catch (err) { console.error('Dashboard fetch error:', err) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  // Show onboarding wizard on first load if the knowledge base is empty
  useEffect(() => {
    if (loading || !stats) return
    const dismissed = localStorage.getItem(ONBOARDING_DISMISSED_KEY) === '1'
    if (!dismissed && stats.documents === 0 && stats.wiki_articles === 0) {
      setShowOnboarding(true)
    }
  }, [loading, stats])

  const dismissOnboarding = () => {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, '1')
    setShowOnboarding(false)
  }

  const handleDataLoaded = () => {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, '1')
    setShowOnboarding(false)
    fetchData()
  }

  if (loading) return <div className="flex items-center justify-center h-screen text-text-tertiary text-sm">Loading...</div>

  const categories = stats ? Object.entries(stats.categories).sort((a, b) => b[1] - a[1]) : []
  const totalDocs = stats?.documents || 0

  // Trend summaries
  const todayIngest = trends.length > 0 ? trends[trends.length - 1].ingest : 0
  const todayWiki = trends.length > 0 ? trends[trends.length - 1].wiki_compile : 0
  const totalIngest14d = trends.reduce((s, d) => s + d.ingest, 0)
  const totalWiki14d = trends.reduce((s, d) => s + d.wiki_compile, 0)

  return (
    <div className="flex flex-col h-screen overflow-y-auto">
      {showOnboarding && (
        <OnboardingWizard
          onDismiss={dismissOnboarding}
          onDataLoaded={handleDataLoaded}
        />
      )}
      <header className="flex items-center px-6 h-14 border-b border-border flex-shrink-0">
        <LayoutDashboard size={16} className="text-accent-primary mr-3" />
        <h1 className="font-heading text-[15px] font-bold text-text-primary">Dashboard</h1>
      </header>

      <div className="p-6 flex flex-col gap-6 max-w-[1100px] mx-auto w-full">
        {/* Top cards */}
        <div className="grid grid-cols-4 gap-4">
          <StatCard icon={<FileText size={16} />} label="Documents" value={stats?.documents || 0} sub={`+${todayIngest} today`} onClick={() => navigate('/knowledge')} />
          <StatCard icon={<BookOpen size={16} />} label="Wiki Articles" value={stats?.wiki_articles || 0} sub={`+${todayWiki} today`} onClick={() => navigate('/wiki')} />
          <StatCard icon={<Bot size={16} />} label="Operations (14d)" value={totalIngest14d + totalWiki14d} sub={`${totalIngest14d} ingest · ${totalWiki14d} wiki`} />
          <StatCard icon={<Calendar size={16} />} label="Schedules" value={stats?.scheduled_tasks || 0} sub="active tasks" />
        </div>

        {/* Trend chart + Categories */}
        <div className="flex gap-6">
          <div className="flex-1 flex flex-col gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">14-Day Activity Trend</span>
            <TrendChart data={trends} />
          </div>
          <div className="w-[280px] flex flex-col gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">Categories</span>
            {categories.length === 0 ? (
              <p className="text-xs text-text-tertiary">No documents classified yet</p>
            ) : (
              <div className="flex flex-col gap-2">
                {categories.map(([cat, count]) => (
                  <div key={cat} className="flex items-center gap-3">
                    <span className="text-xs text-text-primary w-28 truncate">{cat}</span>
                    <div className="flex-1 h-1.5 bg-bg-tertiary rounded-full overflow-hidden">
                      <div className="h-full bg-accent-primary rounded-full" style={{ width: `${Math.max(4, (count / totalDocs) * 100)}%` }} />
                    </div>
                    <span className="text-[10px] font-mono text-text-tertiary w-6 text-right">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Activity + Quick actions */}
        <div className="flex gap-6">
          <div className="flex-1 flex flex-col gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">Recent Activity</span>
            {activity.length === 0 ? (
              <p className="text-xs text-text-tertiary">No activity yet</p>
            ) : (
              <div className="flex flex-col gap-0.5">
                {activity.map((a) => {
                  const op = OP_LABELS[a.operation] || { label: a.operation, color: 'text-gray-600 bg-gray-50' }
                  return (
                    <div key={a.id} className="flex items-start gap-2.5 py-2 border-b border-border last:border-0">
                      <span className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded flex-shrink-0 mt-0.5', op.color)}>{op.label}</span>
                      <div className="flex-1 min-w-0">
                        <span className="text-xs text-text-primary truncate block">{a.doc_title || a.document_id.slice(0, 10)}</span>
                        {a.to_path && (
                          <span className="text-[10px] text-text-tertiary flex items-center gap-1">
                            <ArrowRight size={8} /> {a.to_path.split('/').slice(-2).join('/')}
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-text-tertiary flex-shrink-0 flex items-center gap-1"><Clock size={9} /> {timeAgo(a.created_at)}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
          <div className="w-[280px] flex flex-col gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">Quick Actions</span>
            <div className="flex flex-col gap-2">
              <QuickAction icon={<FolderOpen size={13} />} label="New Workspace Doc" onClick={() => navigate('/workspace')} />
              <QuickAction icon={<FileText size={13} />} label="Browse Knowledge" onClick={() => navigate('/knowledge')} />
              <QuickAction icon={<BookOpen size={13} />} label="Read Wiki" onClick={() => navigate('/wiki')} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Subcomponents ── */

function StatCard({ icon, label, value, sub, onClick }: { icon: React.ReactNode; label: string; value: number; sub: string; onClick?: () => void }) {
  return (
    <button onClick={onClick} className="flex flex-col gap-1.5 p-4 bg-bg-secondary rounded-[10px] border border-border hover:border-accent-primary/30 transition-colors text-left">
      <div className="flex items-center gap-2 text-text-tertiary">{icon}<span className="text-[11px]">{label}</span></div>
      <span className="text-2xl font-heading font-bold text-text-primary">{value}</span>
      <span className="text-[10px] text-text-tertiary">{sub}</span>
    </button>
  )
}

function QuickAction({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex items-center gap-2 px-4 py-2.5 border border-border rounded-[8px] hover:bg-bg-secondary transition-colors">
      <span className="text-accent-primary">{icon}</span>
      <span className="text-xs font-semibold text-text-secondary">{label}</span>
    </button>
  )
}

function TrendChart({ data }: { data: TrendDay[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || data.length === 0) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    ctx.scale(dpr, dpr)
    const w = rect.width
    const h = rect.height

    const pad = { top: 10, right: 20, bottom: 24, left: 30 }
    const cw = w - pad.left - pad.right
    const ch = h - pad.top - pad.bottom

    const maxVal = Math.max(1, ...data.map((d) => d.total))
    // Add inner margin so bars don't touch edges
    const innerPad = 20
    const usableW = cw - innerPad * 2
    const xStep = data.length <= 1 ? 0 : usableW / (data.length - 1)
    const xOffset = pad.left + innerPad

    ctx.clearRect(0, 0, w, h)

    // Grid lines
    ctx.strokeStyle = '#E7E5E4'
    ctx.lineWidth = 0.5
    for (let i = 0; i <= 3; i++) {
      const y = pad.top + (ch / 3) * i
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke()
    }

    // Y-axis labels
    ctx.fillStyle = '#A8A29E'
    ctx.font = '9px system-ui'
    ctx.textAlign = 'right'
    for (let i = 0; i <= 3; i++) {
      const val = Math.round(maxVal * (1 - i / 3))
      ctx.fillText(String(val), pad.left - 4, pad.top + (ch / 3) * i + 3)
    }

    // X-axis labels
    ctx.textAlign = 'center'
    data.forEach((d, i) => {
      if (i % 2 === 0 || i === data.length - 1) {
        ctx.fillText(d.date.slice(5), xOffset + i * xStep, h - 4)
      }
    })

    const drawLine = (key: keyof TrendDay, color: string) => {
      ctx.beginPath()
      ctx.strokeStyle = color
      ctx.lineWidth = 1.5
      data.forEach((d, i) => {
        const x = xOffset + i * xStep
        const y = pad.top + ch - (Number(d[key]) / maxVal) * ch
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.stroke()
    }

    // Draw stacked bars
    data.forEach((d, i) => {
      const x = xOffset + i * xStep - 4
      const barW = 8
      let y = pad.top + ch

      const drawBar = (val: number, color: string) => {
        if (val <= 0) return
        const barH = (val / maxVal) * ch
        y -= barH
        ctx.fillStyle = color
        ctx.globalAlpha = 0.6
        ctx.beginPath()
        ctx.roundRect(x, y, barW, barH, 1)
        ctx.fill()
        ctx.globalAlpha = 1
      }

      drawBar(d.ingest, '#2563EB')
      drawBar(d.wiki_compile, '#16A34A')
      drawBar(d.classify, '#7C3AED')
    })

    // Total line
    drawLine('total', '#F59E0B')

  }, [data])

  if (data.length === 0) {
    return <div className="h-[160px] flex items-center justify-center text-xs text-text-tertiary">No trend data yet</div>
  }

  return (
    <div className="relative">
      <canvas ref={canvasRef} className="w-full h-[160px]" />
      <div className="flex gap-4 mt-2 text-[9px] text-text-tertiary">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[#2563EB] opacity-60" /> Ingest</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[#16A34A] opacity-60" /> Wiki</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[#7C3AED] opacity-60" /> Classify</span>
        <span className="flex items-center gap-1"><span className="w-2 h-1 bg-[#F59E0B]" /> Total</span>
      </div>
    </div>
  )
}
