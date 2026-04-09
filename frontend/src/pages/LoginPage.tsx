import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Shield, FileText, GitFork } from 'lucide-react'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [totp, setTotp] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(account, password, totp)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex bg-bg-primary">
      {/* Left — Branding */}
      <div className="hidden lg:flex flex-col justify-center flex-1 px-16 xl:px-24 bg-bg-secondary border-r border-border">
        <div className="max-w-md">
          <div className="flex items-center gap-2.5 mb-8">
            <img src="/logo.png" alt="PageFly" className="h-9 w-9 rounded-lg" />
            <span className="font-heading text-xl font-bold text-text-primary">PageFly</span>
          </div>

          <p className="text-xs font-semibold uppercase tracking-[1.5px] text-accent-secondary mb-5">
            Personal Knowledge OS
          </p>

          <h1 className="font-heading text-[36px] font-bold text-text-primary leading-tight mb-5">
            Welcome back to your knowledge workspace.
          </h1>

          <p className="text-text-secondary text-[15px] leading-relaxed mb-10">
            Sign in to capture raw notes, distill them into structured insight, and publish searchable wiki knowledge from one warm, reliable system.
          </p>

          <ul className="space-y-4">
            <li className="flex items-start gap-3">
              <div className="mt-0.5 w-7 h-7 rounded-md bg-bg-tertiary flex items-center justify-center flex-shrink-0">
                <FileText size={14} className="text-accent-primary" />
              </div>
              <span className="text-text-secondary text-sm leading-relaxed">
                Private markdown ingestion with metadata preservation
              </span>
            </li>
            <li className="flex items-start gap-3">
              <div className="mt-0.5 w-7 h-7 rounded-md bg-bg-tertiary flex items-center justify-center flex-shrink-0">
                <Shield size={14} className="text-accent-primary" />
              </div>
              <span className="text-text-secondary text-sm leading-relaxed">
                Distillation pipeline for summaries, key claims, and references
              </span>
            </li>
            <li className="flex items-start gap-3">
              <div className="mt-0.5 w-7 h-7 rounded-md bg-bg-tertiary flex items-center justify-center flex-shrink-0">
                <GitFork size={14} className="text-accent-primary" />
              </div>
              <span className="text-text-secondary text-sm leading-relaxed">
                API + graph explorer for downstream automation
              </span>
            </li>
          </ul>
        </div>
      </div>

      {/* Right — Form */}
      <div className="flex flex-col justify-center flex-1 px-8 sm:px-12 lg:px-16 xl:px-20">
        <div className="w-full max-w-sm mx-auto">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-2.5 mb-10">
            <img src="/logo.png" alt="PageFly" className="h-8 w-8 rounded-lg" />
            <span className="font-heading text-lg font-bold text-text-primary">PageFly</span>
          </div>

          <h2 className="font-heading text-[28px] font-bold text-text-primary mb-1.5">Log in</h2>
          <p className="text-text-secondary text-sm mb-8">
            Account, password, and TOTP verification.
          </p>

          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <label className="flex flex-col gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[1.5px] text-text-secondary">
                Account
              </span>
              <input
                type="text"
                value={account}
                onChange={(e) => setAccount(e.target.value)}
                placeholder="you@pagefly.ink"
                className="w-full px-4 py-3 rounded-[6px] border border-border bg-bg-primary text-text-primary text-sm placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary/20 transition-all"
                required
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[1.5px] text-text-secondary">
                Password
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-[6px] border border-border bg-bg-primary text-text-primary text-sm placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary/20 transition-all"
                required
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[1.5px] text-text-secondary">
                TOTP 2FA
              </span>
              <input
                type="text"
                value={totp}
                onChange={(e) => setTotp(e.target.value.replace(/\D/g, ''))}
                placeholder="123456"
                maxLength={6}
                inputMode="numeric"
                className="w-full px-4 py-3 rounded-[6px] border border-border bg-bg-primary text-text-primary text-sm tracking-[6px] font-mono placeholder:tracking-[6px] placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary/20 transition-all"
                required
              />
            </label>

            {error && (
              <div className="text-error text-sm bg-error/5 border border-error/20 rounded-[6px] px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="mt-3 w-full py-3.5 rounded-[12px] bg-accent-primary text-bg-primary font-semibold text-sm hover:bg-accent-secondary transition-colors disabled:opacity-60 shadow-sm cursor-pointer"
            >
              {loading ? 'Signing in...' : 'Log in'}
            </button>
          </form>

          <div className="flex items-center justify-between mt-5 text-xs text-text-tertiary">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" className="rounded accent-accent-primary" />
              <span>Remember this device</span>
            </label>
            <button className="text-accent-secondary hover:underline">Forgot password?</button>
          </div>

          <p className="mt-10 text-center text-xs text-text-tertiary flex items-center justify-center gap-1.5">
            <Shield size={11} />
            Session security: JWT + scoped API tokens enabled
          </p>
        </div>
      </div>
    </div>
  )
}
