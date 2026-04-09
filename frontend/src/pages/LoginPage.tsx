import { useState, useEffect, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Shield, FileText, GitFork, Loader2 } from 'lucide-react'
import api from '@/api/client'

type Step = 'password' | 'totp' | 'email'

export function LoginPage() {
  const { setToken } = useAuth()
  const navigate = useNavigate()

  const [steps, setSteps] = useState<Step[]>([])
  const [currentStep, setCurrentStep] = useState<Step>('password')
  const [sessionToken, setSessionToken] = useState('')

  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [emailCode, setEmailCode] = useState('')

  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [emailSent, setEmailSent] = useState(false)

  useEffect(() => {
    api.get('/api/auth/config').then(({ data }) => {
      if (data.configured) {
        setSteps(data.steps)
      }
    }).catch(() => {})
  }, [])

  const handlePasswordSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/api/auth/login', { account, password })
      if (data.status === 'complete') {
        setToken(data.token)
        navigate('/dashboard')
      } else {
        setSessionToken(data.session_token)
        setCurrentStep(data.next_step)
      }
    } catch {
      setError('Invalid account or password')
    } finally {
      setLoading(false)
    }
  }

  const handleTotpSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/api/auth/verify-totp', {
        code: totpCode,
        session_token: sessionToken,
      })
      if (data.status === 'complete') {
        setToken(data.token)
        navigate('/dashboard')
      } else {
        setCurrentStep(data.next_step)
      }
    } catch {
      setError('Invalid TOTP code')
    } finally {
      setLoading(false)
    }
  }

  const handleSendEmailCode = async () => {
    setError('')
    setLoading(true)
    try {
      await api.post('/api/auth/send-email-code', { session_token: sessionToken })
      setEmailSent(true)
    } catch {
      setError('Failed to send verification email')
    } finally {
      setLoading(false)
    }
  }

  const handleEmailSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/api/auth/verify-email', {
        code: emailCode,
        session_token: sessionToken,
      })
      if (data.status === 'complete') {
        setToken(data.token)
        navigate('/dashboard')
      }
    } catch {
      setError('Invalid or expired verification code')
    } finally {
      setLoading(false)
    }
  }

  const stepLabels: Record<Step, string> = {
    password: 'Account & Password',
    totp: '2FA Verification',
    email: 'Email Verification',
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
          <div className="lg:hidden flex items-center gap-2.5 mb-10">
            <img src="/logo.png" alt="PageFly" className="h-8 w-8 rounded-lg" />
            <span className="font-heading text-lg font-bold text-text-primary">PageFly</span>
          </div>

          <h2 className="font-heading text-[28px] font-bold text-text-primary mb-1.5">Log in</h2>
          <p className="text-text-secondary text-sm mb-8">
            {stepLabels[currentStep]}
            {steps.length > 1 && (
              <span className="text-text-tertiary ml-2">
                ({steps.indexOf(currentStep) + 1}/{steps.length})
              </span>
            )}
          </p>

          {/* Step 1: Password */}
          {currentStep === 'password' && (
            <form onSubmit={handlePasswordSubmit} className="flex flex-col gap-5">
              <label className="flex flex-col gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[1.5px] text-text-secondary">Account</span>
                <input
                  type="text"
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                  placeholder="you@pagefly.ink"
                  className="w-full px-4 py-3 rounded-[6px] border border-border bg-bg-primary text-text-primary text-sm placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary/20 transition-all"
                  required
                  autoFocus
                />
              </label>

              <label className="flex flex-col gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[1.5px] text-text-secondary">Password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-4 py-3 rounded-[6px] border border-border bg-bg-primary text-text-primary text-sm placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary/20 transition-all"
                  required
                />
              </label>

              {error && <ErrorBox message={error} />}

              <SubmitButton loading={loading} label="Continue" />
            </form>
          )}

          {/* Step 2: TOTP */}
          {currentStep === 'totp' && (
            <form onSubmit={handleTotpSubmit} className="flex flex-col gap-5">
              <label className="flex flex-col gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[1.5px] text-text-secondary">TOTP 2FA Code</span>
                <input
                  type="text"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  placeholder="123456"
                  maxLength={6}
                  inputMode="numeric"
                  className="w-full px-4 py-3 rounded-[6px] border border-border bg-bg-primary text-text-primary text-sm tracking-[6px] font-mono placeholder:tracking-[6px] placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary/20 transition-all"
                  required
                  autoFocus
                />
              </label>

              <p className="text-text-tertiary text-xs">Enter the 6-digit code from your authenticator app.</p>

              {error && <ErrorBox message={error} />}

              <SubmitButton loading={loading} label="Verify" />
            </form>
          )}

          {/* Step 3: Email Code */}
          {currentStep === 'email' && (
            <form onSubmit={handleEmailSubmit} className="flex flex-col gap-5">
              {!emailSent ? (
                <>
                  <p className="text-text-secondary text-sm">
                    We'll send a verification code to <strong>{account}</strong>.
                  </p>
                  <button
                    type="button"
                    onClick={handleSendEmailCode}
                    disabled={loading}
                    className="w-full py-3.5 rounded-[12px] bg-accent-primary text-bg-primary font-semibold text-sm hover:bg-accent-secondary transition-colors disabled:opacity-60 shadow-sm cursor-pointer"
                  >
                    {loading ? <Loader2 size={16} className="animate-spin mx-auto" /> : 'Send Verification Code'}
                  </button>
                </>
              ) : (
                <>
                  <label className="flex flex-col gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-[1.5px] text-text-secondary">Email Code</span>
                    <input
                      type="text"
                      value={emailCode}
                      onChange={(e) => setEmailCode(e.target.value.replace(/\D/g, ''))}
                      placeholder="123456"
                      maxLength={6}
                      inputMode="numeric"
                      className="w-full px-4 py-3 rounded-[6px] border border-border bg-bg-primary text-text-primary text-sm tracking-[6px] font-mono placeholder:tracking-[6px] placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary/20 transition-all"
                      required
                      autoFocus
                    />
                  </label>

                  <p className="text-text-tertiary text-xs">
                    Code sent to {account}. Expires in 5 minutes.
                    <button type="button" onClick={handleSendEmailCode} className="text-accent-secondary ml-1 hover:underline">
                      Resend
                    </button>
                  </p>

                  {error && <ErrorBox message={error} />}

                  <SubmitButton loading={loading} label="Verify" />
                </>
              )}
            </form>
          )}

          <p className="mt-10 text-center text-xs text-text-tertiary flex items-center justify-center gap-1.5">
            <Shield size={11} />
            Session security: JWT + scoped API tokens enabled
          </p>
        </div>
      </div>
    </div>
  )
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="text-error text-sm bg-error/5 border border-error/20 rounded-[6px] px-3 py-2">
      {message}
    </div>
  )
}

function SubmitButton({ loading, label }: { loading: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="mt-3 w-full py-3.5 rounded-[12px] bg-accent-primary text-bg-primary font-semibold text-sm hover:bg-accent-secondary transition-colors disabled:opacity-60 shadow-sm cursor-pointer flex items-center justify-center gap-2"
    >
      {loading ? <Loader2 size={16} className="animate-spin" /> : label}
    </button>
  )
}
