import { useState, useEffect, useCallback, useRef } from 'react'
import { MessageCircle, Send, RotateCcw, Bot, User } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '@/api/client'
import { cn } from '@/lib/utils'

interface Message {
  role: 'user' | 'assistant'
  content: string
  ts?: string
}

const SLASH_COMMANDS = [
  { cmd: '/search', desc: 'Search documents by keyword', args: '<keyword>' },
  { cmd: '/status', desc: 'Show knowledge base stats', args: '' },
  { cmd: '/save', desc: 'Save conversation as memo', args: '' },
  { cmd: '/reset', desc: 'Clear conversation context', args: '' },
]

export function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [showCommands, setShowCommands] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const scrollToBottom = () => {
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }), 50)
  }

  const fetchHistory = useCallback(async () => {
    try {
      const { data } = await api.get('/api/chat/history')
      setMessages(data.messages || [])
      scrollToBottom()
    } catch { /* silent */ }
  }, [])

  useEffect(() => { fetchHistory() }, [fetchHistory])
  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSend = async () => {
    const msg = input.trim()
    if (!msg || sending) return
    setInput('')
    setShowCommands(false)
    setSending(true)

    // Handle local /reset command
    if (msg === '/reset') {
      try {
        await api.post('/api/chat/reset')
        setMessages([])
      } catch { /* silent */ }
      setSending(false)
      return
    }

    // Optimistic add user message
    const userMsg: Message = { role: 'user', content: msg }
    setMessages((prev) => [...prev, userMsg])
    scrollToBottom()

    try {
      const { data } = await api.post('/api/chat', { message: msg })
      setMessages(data.messages || [])
      scrollToBottom()
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Something went wrong. Please try again.' }])
    } finally { setSending(false) }
  }

  const handleInputChange = (value: string) => {
    setInput(value)
    setShowCommands(value === '/')
  }

  const selectCommand = (cmd: string) => {
    setInput(cmd + ' ')
    setShowCommands(false)
    inputRef.current?.focus()
  }

  const handleReset = async () => {
    if (messages.length === 0 || !confirm('Clear all chat history? This also clears Telegram history.')) return
    try {
      await api.post('/api/chat/reset')
      setMessages([])
    } catch { /* silent */ }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <MessageCircle size={16} className="text-accent-primary" />
          <h1 className="font-heading text-[15px] font-bold text-text-primary">Chat</h1>
          <span className="text-xs text-text-tertiary">{messages.length} messages · shared with Telegram</span>
        </div>
        <button onClick={handleReset} className="flex items-center gap-1.5 px-3 py-1.5 border border-border rounded-[6px] text-[11px] text-text-secondary hover:bg-bg-secondary transition-colors">
          <RotateCcw size={11} /> Reset
        </button>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="max-w-[760px] mx-auto px-6 py-6 flex flex-col gap-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-text-tertiary gap-3">
              <Bot size={40} className="opacity-20" />
              <p className="text-sm">Ask anything about your knowledge base</p>
              <p className="text-xs">Conversations are shared with your Telegram bot</p>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={cn('flex gap-3', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
                {msg.role === 'assistant' && (
                  <div className="w-7 h-7 rounded-full bg-accent-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Bot size={14} className="text-accent-primary" />
                  </div>
                )}
                <div className={cn(
                  'max-w-[85%] rounded-[12px] px-4 py-3',
                  msg.role === 'user'
                    ? 'bg-accent-primary text-bg-primary'
                    : 'bg-bg-secondary border border-border'
                )}>
                  {msg.role === 'user' ? (
                    <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <article className="prose-pagefly text-sm [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </article>
                  )}
                </div>
                {msg.role === 'user' && (
                  <div className="w-7 h-7 rounded-full bg-bg-tertiary flex items-center justify-center flex-shrink-0 mt-0.5">
                    <User size={14} className="text-text-secondary" />
                  </div>
                )}
              </div>
            ))
          )}
          {sending && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-full bg-accent-primary/10 flex items-center justify-center flex-shrink-0">
                <Bot size={14} className="text-accent-primary animate-pulse" />
              </div>
              <div className="bg-bg-secondary border border-border rounded-[12px] px-4 py-3">
                <span className="text-xs text-text-tertiary">Thinking...</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border px-6 py-4 flex-shrink-0">
        <div className="max-w-[760px] mx-auto relative">
          {/* Slash command dropdown */}
          {showCommands && (
            <div className="absolute bottom-full mb-2 left-0 w-80 bg-bg-secondary border border-border rounded-[10px] shadow-lg overflow-hidden">
              {SLASH_COMMANDS.map((c) => (
                <button
                  key={c.cmd}
                  onClick={() => selectCommand(c.cmd)}
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-bg-tertiary transition-colors text-left"
                >
                  <code className="text-xs font-mono text-accent-primary">{c.cmd}</code>
                  <span className="text-xs text-text-secondary">{c.desc}</span>
                  {c.args && <span className="text-[10px] text-text-tertiary ml-auto">{c.args}</span>}
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-3">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your knowledge base... (/ for commands)"
              rows={1}
              className="flex-1 px-4 py-3 border border-border rounded-[10px] bg-bg-primary text-sm text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary resize-none"
              disabled={sending}
            />
            <button
              onClick={handleSend}
              disabled={sending || !input.trim()}
              className="px-4 py-3 bg-accent-primary rounded-[10px] text-bg-primary hover:bg-accent-secondary transition-colors disabled:opacity-40 flex-shrink-0"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
