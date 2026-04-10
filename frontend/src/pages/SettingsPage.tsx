import { useState, useEffect, useCallback } from 'react'
import { Settings, Shield, FolderTree, Server, Lock, Eye, EyeOff, Plus, Pencil, Trash2, Check, X } from 'lucide-react'
import api from '@/api/client'

interface Stats {
  documents: number
  wiki_articles: number
  operations: number
  scheduled_tasks: number
  custom_prompts: number
  categories: Record<string, number>
}

export function SettingsPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [pwMsg, setPwMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)
  const [pwLoading, setPwLoading] = useState(false)

  useEffect(() => {
    api.get('/api/stats').then(({ data }) => setStats(data)).catch(() => {})
  }, [])

  const handleChangePassword = useCallback(async () => {
    if (!oldPassword || !newPassword) return
    if (newPassword.length < 6) { setPwMsg({ type: 'err', text: 'Password must be at least 6 characters' }); return }
    setPwLoading(true)
    setPwMsg(null)
    try {
      await api.post('/api/auth/change-password', { old_password: oldPassword, new_password: newPassword })
      setPwMsg({ type: 'ok', text: 'Password changed successfully' })
      setOldPassword('')
      setNewPassword('')
    } catch (e: any) {
      setPwMsg({ type: 'err', text: e.response?.data?.detail || 'Failed to change password' })
    } finally { setPwLoading(false) }
  }, [oldPassword, newPassword])

  const baseUrl = import.meta.env.VITE_API_URL || window.location.origin

  return (
    <div className="flex flex-col h-screen overflow-y-auto">
      <header className="flex items-center px-6 h-14 border-b border-border flex-shrink-0">
        <Settings size={16} className="text-accent-primary mr-3" />
        <h1 className="font-heading text-[15px] font-bold text-text-primary">Settings</h1>
      </header>

      <div className="p-6 flex flex-col gap-8 max-w-[700px] mx-auto w-full">
        {/* Account */}
        <Section icon={<Lock size={14} />} title="Account">
          <div className="flex flex-col gap-3">
            <label className="text-[11px] text-text-tertiary">Change Password</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  placeholder="Current password"
                  className="w-full px-3 py-2 text-xs border border-border rounded-[6px] bg-bg-primary text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary"
                />
              </div>
              <div className="relative flex-1">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="New password"
                  className="w-full px-3 py-2 text-xs border border-border rounded-[6px] bg-bg-primary text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary pr-8"
                />
                <button onClick={() => setShowPassword(!showPassword)} className="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary">
                  {showPassword ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
              </div>
              <button onClick={handleChangePassword} disabled={pwLoading} className="px-4 py-2 bg-accent-primary rounded-[6px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60">
                {pwLoading ? '...' : 'Update'}
              </button>
            </div>
            {pwMsg && (
              <span className={`text-[11px] ${pwMsg.type === 'ok' ? 'text-success' : 'text-error'}`}>{pwMsg.text}</span>
            )}
          </div>
        </Section>

        {/* 2FA */}
        <Section icon={<Shield size={14} />} title="Two-Factor Authentication">
          <div className="flex items-center justify-between p-3 bg-bg-secondary rounded-[8px]">
            <div>
              <p className="text-xs font-medium text-text-primary">TOTP Authenticator</p>
              <p className="text-[10px] text-text-tertiary mt-0.5">Configure in config.json → auth.totp_secret</p>
            </div>
            <span className="text-[10px] font-bold px-2 py-1 rounded bg-bg-tertiary text-text-tertiary">
              Configure via config.json
            </span>
          </div>
        </Section>

        {/* Categories */}
        <Section icon={<FolderTree size={14} />} title="Knowledge Categories">
          <CategoryEditor docCounts={stats?.categories || {}} />
        </Section>

        {/* System */}
        <Section icon={<Server size={14} />} title="System Info">
          <div className="flex flex-col gap-1.5">
            <InfoRow label="API Base URL" value={baseUrl} />
            <InfoRow label="Documents" value={String(stats?.documents || 0)} />
            <InfoRow label="Wiki Articles" value={String(stats?.wiki_articles || 0)} />
            <InfoRow label="Operations Logged" value={String(stats?.operations || 0)} />
            <InfoRow label="Scheduled Tasks" value={String(stats?.scheduled_tasks || 0)} />
            <InfoRow label="Custom Prompts" value={String(stats?.custom_prompts || 0)} />
          </div>
        </Section>
      </div>
    </div>
  )
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-accent-primary">{icon}</span>
        <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">{title}</span>
      </div>
      {children}
    </div>
  )
}

function CategoryEditor({ docCounts }: { docCounts: Record<string, number> }) {
  const [categories, setCategories] = useState<{ id: string; name: string }[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [newId, setNewId] = useState('')
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const fetchCategories = useCallback(async () => {
    try {
      const { data } = await api.get('/api/categories')
      setCategories(data.categories || [])
    } catch { /* silent */ }
  }, [])

  useEffect(() => { fetchCategories() }, [fetchCategories])

  const handleAdd = async () => {
    if (!newId.trim() || !newName.trim()) return
    setLoading(true)
    setMsg(null)
    try {
      await api.post('/api/categories', { id: newId.trim().toLowerCase().replace(/\s+/g, '-'), name: newName.trim() })
      setNewId('')
      setNewName('')
      await fetchCategories()
      setMsg({ type: 'ok', text: 'Category added' })
    } catch (e: any) { setMsg({ type: 'err', text: e.response?.data?.detail || 'Failed' }) }
    finally { setLoading(false) }
  }

  const handleRename = async (oldId: string) => {
    if (!editValue.trim() || editValue === oldId) { setEditingId(null); return }
    setLoading(true)
    setMsg(null)
    try {
      await api.put(`/api/categories/${oldId}`, { new_id: editValue.trim().toLowerCase().replace(/\s+/g, '-') })
      setEditingId(null)
      await fetchCategories()
      setMsg({ type: 'ok', text: `Renamed "${oldId}" → "${editValue.trim()}" (including all documents, metadata, and files)` })
    } catch (e: any) { setMsg({ type: 'err', text: e.response?.data?.detail || 'Failed' }) }
    finally { setLoading(false) }
  }

  const handleDelete = async (catId: string) => {
    const count = docCounts[catId] || 0
    const others = categories.filter((c) => c.id !== catId)

    if (count > 0 && others.length > 0) {
      const target = prompt(
        `Category "${catId}" has ${count} documents.\n\nMerge them into which category?\n\nOptions: ${others.map((c) => c.id).join(', ')}\n\n(Leave empty to just remove the category from config)`
      )
      if (target === null) return // cancelled
      setLoading(true)
      try {
        const params = target.trim() ? `?merge_into=${encodeURIComponent(target.trim())}` : ''
        await api.delete(`/api/categories/${catId}${params}`)
        await fetchCategories()
        setMsg({ type: 'ok', text: target.trim() ? `"${catId}" merged into "${target.trim()}" (${count} docs moved)` : `Category "${catId}" removed` })
      } catch (e: any) { setMsg({ type: 'err', text: e.response?.data?.detail || 'Failed' }) }
      finally { setLoading(false) }
    } else {
      if (!confirm(`Delete category "${catId}"?`)) return
      setLoading(true)
      try {
        await api.delete(`/api/categories/${catId}`)
        await fetchCategories()
        setMsg({ type: 'ok', text: `Category "${catId}" removed` })
      } catch (e: any) { setMsg({ type: 'err', text: e.response?.data?.detail || 'Failed' }) }
      finally { setLoading(false) }
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Category list */}
      {categories.map((cat) => {
        const count = docCounts[cat.id] || 0
        return (
          <div key={cat.id} className="group flex items-center gap-2 px-3 py-2 bg-bg-secondary rounded-[6px]">
            {editingId === cat.id ? (
              <>
                <input
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleRename(cat.id); if (e.key === 'Escape') setEditingId(null) }}
                  className="flex-1 text-xs bg-bg-primary border border-accent-primary rounded px-2 py-1 outline-none"
                  autoFocus
                />
                <button onClick={() => handleRename(cat.id)} disabled={loading} className="p-1 text-success"><Check size={12} /></button>
                <button onClick={() => setEditingId(null)} className="p-1 text-text-tertiary"><X size={12} /></button>
              </>
            ) : (
              <>
                <span className="flex-1 text-xs text-text-primary">{cat.id}</span>
                <span className="text-[10px] text-text-tertiary">{cat.name}</span>
                {count > 0 && <span className="text-[9px] font-mono text-text-tertiary bg-bg-tertiary px-1.5 py-0.5 rounded">{count}</span>}
                <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => { setEditingId(cat.id); setEditValue(cat.id) }} className="p-1 text-text-tertiary hover:text-accent-primary"><Pencil size={10} /></button>
                  <button onClick={() => handleDelete(cat.id)} className="p-1 text-text-tertiary hover:text-error"><Trash2 size={10} /></button>
                </div>
              </>
            )}
          </div>
        )
      })}

      {/* Add new */}
      <div className="flex gap-2">
        <input value={newId} onChange={(e) => setNewId(e.target.value)} placeholder="ID (e.g. machine-learning)" className="flex-1 px-3 py-2 text-xs border border-border rounded-[6px] bg-bg-primary text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary" />
        <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Display name" className="flex-1 px-3 py-2 text-xs border border-border rounded-[6px] bg-bg-primary text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary" />
        <button onClick={handleAdd} disabled={loading || !newId.trim() || !newName.trim()} className="flex items-center gap-1 px-3 py-2 bg-accent-primary rounded-[6px] text-xs font-semibold text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-60">
          <Plus size={12} /> Add
        </button>
      </div>

      {msg && <span className={`text-[11px] ${msg.type === 'ok' ? 'text-success' : 'text-error'}`}>{msg.text}</span>}

      <p className="text-[10px] text-text-tertiary">Renaming a category updates config, database, filesystem, and all metadata files automatically.</p>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 bg-bg-secondary rounded-[6px]">
      <span className="text-xs text-text-tertiary">{label}</span>
      <span className="text-xs font-mono text-text-primary">{value}</span>
    </div>
  )
}
