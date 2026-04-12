import { useState, useRef } from 'react'
import { Sparkles, Upload, Loader2, CheckCircle2, X, BookOpen } from 'lucide-react'
import api from '@/api/client'

interface Props {
  onDismiss: () => void
  onDataLoaded: () => void
}

/**
 * First-run wizard shown when the dashboard has zero documents.
 * Offers two paths:
 *   1. Load demo data (one click, sees a working knowledge base instantly)
 *   2. Upload your own file (PDF / text / markdown / image / audio)
 */
export function OnboardingWizard({ onDismiss, onDataLoaded }: Props) {
  const [loading, setLoading] = useState<'demo' | 'upload' | null>(null)
  const [success, setSuccess] = useState<'demo' | 'upload' | null>(null)
  const [error, setError] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleLoadDemo = async () => {
    setError('')
    setLoading('demo')
    try {
      await api.post('/api/demo/load')
      setSuccess('demo')
      setTimeout(() => onDataLoaded(), 800)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Failed to load demo data')
    } finally {
      setLoading(null)
    }
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    setLoading('upload')
    try {
      const formData = new FormData()
      formData.append('file', file)
      await api.post('/api/ingest', formData)
      setSuccess('upload')
      setTimeout(() => onDataLoaded(), 1500)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Upload failed')
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-bg-primary border border-border rounded-[14px] max-w-[560px] w-full shadow-xl relative">
        <button
          onClick={onDismiss}
          className="absolute top-4 right-4 text-text-tertiary hover:text-text-primary transition-colors"
          aria-label="Dismiss"
        >
          <X size={16} />
        </button>

        <div className="p-8">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles size={16} className="text-accent-primary" />
            <span className="text-[10px] font-bold uppercase tracking-[1.5px] text-accent-primary">
              Welcome to PageFly
            </span>
          </div>

          <h2 className="font-heading text-xl font-bold text-text-primary mb-2">
            Let&rsquo;s put something in your knowledge base
          </h2>
          <p className="text-sm text-text-tertiary mb-6">
            PageFly works best once it has a few documents to compile. Pick a starting point:
          </p>

          {/* Option 1: Demo data */}
          <button
            onClick={handleLoadDemo}
            disabled={loading !== null || success !== null}
            className="w-full flex items-start gap-4 p-5 border border-border rounded-[10px] hover:border-accent-primary/40 hover:bg-bg-secondary transition-colors text-left mb-3 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <span className="text-accent-primary mt-0.5">
              {loading === 'demo' ? <Loader2 size={18} className="animate-spin" /> :
               success === 'demo' ? <CheckCircle2 size={18} /> :
               <BookOpen size={18} />}
            </span>
            <div className="flex-1">
              <div className="font-semibold text-sm text-text-primary mb-1">
                Load the demo knowledge base
                <span className="ml-2 text-[10px] font-normal text-text-tertiary">recommended</span>
              </div>
              <div className="text-xs text-text-tertiary leading-relaxed">
                3 sample documents on knowledge management + 5 auto-compiled wiki articles,
                already cross-referenced. See exactly how the system works in one click.
              </div>
            </div>
          </button>

          {/* Option 2: Upload */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={loading !== null || success !== null}
            className="w-full flex items-start gap-4 p-5 border border-border rounded-[10px] hover:border-accent-primary/40 hover:bg-bg-secondary transition-colors text-left disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <span className="text-accent-primary mt-0.5">
              {loading === 'upload' ? <Loader2 size={18} className="animate-spin" /> :
               success === 'upload' ? <CheckCircle2 size={18} /> :
               <Upload size={18} />}
            </span>
            <div className="flex-1">
              <div className="font-semibold text-sm text-text-primary mb-1">
                Upload your own file
              </div>
              <div className="text-xs text-text-tertiary leading-relaxed">
                PDF, Markdown, text, image, or audio. The system will classify it and the
                Compiler Agent will start writing wiki pages. Takes ~30 seconds.
              </div>
            </div>
          </button>

          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.md,.markdown,.docx,.doc,.png,.jpg,.jpeg,.webp,.mp3,.m4a,.wav,.ogg"
            className="hidden"
            onChange={handleFileSelect}
          />

          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-[8px] text-xs text-red-700">
              {error}
            </div>
          )}

          {success === 'upload' && (
            <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-[8px] text-xs text-green-700">
              File uploaded. Classification is running in the background — refresh in ~30s.
            </div>
          )}

          <button
            onClick={onDismiss}
            className="mt-6 text-xs text-text-tertiary hover:text-text-primary transition-colors"
          >
            Skip for now
          </button>
        </div>
      </div>
    </div>
  )
}
