import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { LayoutDashboard, FileText, BookOpen, GitFork, Clock, FolderOpen, Calendar, ArrowRight } from 'lucide-react'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface Stats {
  documents: number
  wiki_articles: number
  operations: number
  scheduled_tasks: number
  custom_prompts: number
  categories: Record<string, number>
}

interface Activity {
  id: number
  document_id: string
  operation: string
  from_path: string
  to_path: string
  created_at: string
  doc_title: string | null
}

const OP_LABELS: Record<string, { label: string; color: string }> = {
  ingest: { label: 'Ingested', color: 'text-blue-600 bg-blue-50' },
  classify: { label: 'Classified', color: 'text-purple-600 bg-purple-50' },
  move: { label: 'Moved', color: 'text-amber-600 bg-amber-50' },
  delete: { label: 'Deleted', color: 'text-red-600 bg-red-50' },
  wiki_compile: { label: 'Wiki compiled', color: 'text-green-600 bg-green-50' },
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [activity, setActivity] = useState<Activity[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const fetchData = useCallback(async () => {
    try {
      const [statsRes, actRes] = await Promise.all([
        api.get('/api/stats'),
        api.get('/api/activity?limit=20'),
      ])
      setStats(statsRes.data)
      setActivity(actRes.data.activity || [])
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) {
    return <div className="flex items-center justify-center h-screen text-text-tertiary text-sm">Loading...</div>
  }

  const categories = stats ? Object.entries(stats.categories).sort((a, b) => b[1] - a[1]) : []
  const totalDocs = stats?.documents || 0

  return (
    <div className="flex flex-col h-screen overflow-y-auto">
      <header className="flex items-center px-6 h-14 border-b border-border flex-shrink-0">
        <LayoutDashboard size={16} className="text-accent-primary mr-3" />
        <h1 className="font-heading text-[15px] font-bold text-text-primary">Dashboard</h1>
      </header>

      <div className="p-6 flex flex-col gap-6 max-w-[1100px]">
        {/* Stat cards */}
        <div className="grid grid-cols-4 gap-4">
          <StatCard icon={<FileText size={16} />} label="Documents" value={stats?.documents || 0} onClick={() => navigate('/knowledge')} />
          <StatCard icon={<BookOpen size={16} />} label="Wiki Articles" value={stats?.wiki_articles || 0} onClick={() => navigate('/wiki')} />
          <StatCard icon={<GitFork size={16} />} label="Graph Nodes" value={(stats?.documents || 0) + (stats?.wiki_articles || 0)} onClick={() => navigate('/graph')} />
          <StatCard icon={<Calendar size={16} />} label="Schedules" value={stats?.scheduled_tasks || 0} />
        </div>

        <div className="flex gap-6">
          {/* Categories breakdown */}
          <div className="flex-1 flex flex-col gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">Categories</span>
            {categories.length === 0 ? (
              <p className="text-xs text-text-tertiary">No documents classified yet</p>
            ) : (
              <div className="flex flex-col gap-2">
                {categories.map(([cat, count]) => (
                  <div key={cat} className="flex items-center gap-3">
                    <span className="text-xs text-text-primary w-32 truncate">{cat}</span>
                    <div className="flex-1 h-2 bg-bg-tertiary rounded-full overflow-hidden">
                      <div
                        className="h-full bg-accent-primary rounded-full transition-all"
                        style={{ width: `${Math.max(4, (count / totalDocs) * 100)}%` }}
                      />
                    </div>
                    <span className="text-[11px] font-mono text-text-tertiary w-8 text-right">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Activity timeline */}
          <div className="w-[400px] flex flex-col gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">Recent Activity</span>
            {activity.length === 0 ? (
              <p className="text-xs text-text-tertiary">No activity yet</p>
            ) : (
              <div className="flex flex-col gap-1">
                {activity.map((a) => {
                  const op = OP_LABELS[a.operation] || { label: a.operation, color: 'text-gray-600 bg-gray-50' }
                  return (
                    <div key={a.id} className="flex items-start gap-2.5 py-2 border-b border-border last:border-0">
                      <span className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded flex-shrink-0 mt-0.5', op.color)}>
                        {op.label}
                      </span>
                      <div className="flex-1 min-w-0">
                        <span className="text-xs text-text-primary truncate block">{a.doc_title || a.document_id.slice(0, 10)}</span>
                        {a.to_path && (
                          <span className="text-[10px] text-text-tertiary flex items-center gap-1">
                            <ArrowRight size={8} /> {a.to_path.split('/').slice(-2).join('/')}
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-text-tertiary flex-shrink-0 flex items-center gap-1">
                        <Clock size={9} /> {timeAgo(a.created_at)}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* Quick actions */}
        <div className="flex flex-col gap-3">
          <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">Quick Actions</span>
          <div className="flex gap-3">
            <QuickAction icon={<FolderOpen size={14} />} label="New Workspace Doc" onClick={() => navigate('/workspace')} />
            <QuickAction icon={<FileText size={14} />} label="Browse Knowledge" onClick={() => navigate('/knowledge')} />
            <QuickAction icon={<BookOpen size={14} />} label="Read Wiki" onClick={() => navigate('/wiki')} />
            <QuickAction icon={<GitFork size={14} />} label="View Graph" onClick={() => navigate('/graph')} />
          </div>
        </div>
      </div>
    </div>
  )
}

function StatCard({ icon, label, value, onClick }: { icon: React.ReactNode; label: string; value: number; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col gap-2 p-4 bg-bg-secondary rounded-[10px] border border-border hover:border-accent-primary/30 transition-colors text-left"
    >
      <div className="flex items-center gap-2 text-text-tertiary">{icon}<span className="text-[11px]">{label}</span></div>
      <span className="text-2xl font-heading font-bold text-text-primary">{value}</span>
    </button>
  )
}

function QuickAction({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 px-4 py-3 border border-border rounded-[8px] hover:bg-bg-secondary transition-colors"
    >
      <span className="text-accent-primary">{icon}</span>
      <span className="text-xs font-semibold text-text-secondary">{label}</span>
    </button>
  )
}
