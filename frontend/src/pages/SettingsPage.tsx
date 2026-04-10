import { useState, useEffect, useCallback } from 'react'
import { Settings, Shield, FolderTree, Server, Lock, Eye, EyeOff } from 'lucide-react'
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
          {stats ? (
            <div className="flex flex-col gap-1.5">
              {Object.entries(stats.categories).sort((a, b) => b[1] - a[1]).map(([cat, count]) => (
                <div key={cat} className="flex items-center justify-between px-3 py-2 bg-bg-secondary rounded-[6px]">
                  <span className="text-xs text-text-primary">{cat}</span>
                  <span className="text-[10px] font-mono text-text-tertiary">{count} docs</span>
                </div>
              ))}
              {Object.keys(stats.categories).length === 0 && (
                <p className="text-xs text-text-tertiary">No categories yet. Documents get classified automatically on ingest.</p>
              )}
              <p className="text-[10px] text-text-tertiary mt-1">Edit categories in config/categories.json</p>
            </div>
          ) : (
            <p className="text-xs text-text-tertiary">Loading...</p>
          )}
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

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 bg-bg-secondary rounded-[6px]">
      <span className="text-xs text-text-tertiary">{label}</span>
      <span className="text-xs font-mono text-text-primary">{value}</span>
    </div>
  )
}
