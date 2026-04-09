import { useState } from 'react'

function GithubIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
    </svg>
  )
}

const FEATURES = [
  { image: '/assets/feature-1.png', title: 'Capture', desc: 'Ingest PDFs, markdown, images, voice memos, and URLs into a structured raw layer.' },
  { image: '/assets/feature-2.png', title: 'Distill', desc: 'AI classifies, scores relevance, tags temporal type, and extracts key claims automatically.' },
  { image: '/assets/feature-3.png', title: 'Compile', desc: 'Agents compile wiki articles — concept pages, summaries, and connection maps — with update-first governance.' },
  { image: '/assets/feature-4.png', title: 'Telegram Bot', desc: 'Send text, photos, voice, documents via Telegram. Approval flow with inline keyboard.' },
  { image: '/assets/feature-5.png', title: 'REST API', desc: 'Full REST API with scoped tokens for downstream automation and integrations.' },
  { image: '/assets/feature-6.png', title: 'Obsidian-Compatible', desc: 'Wiki output as flat markdown files with YAML frontmatter — drop into Obsidian or any PKM tool.' },
] as const


function FeatureGrid() {
  const [active, setActive] = useState<number | null>(null)

  return (
    <section className="max-w-6xl mx-auto px-5 md:px-8 pb-14 md:pb-28">
      <div className="grid grid-cols-3 gap-3 md:gap-7">
        {FEATURES.map(({ image, title, desc }, i) => (
          <div
            key={title}
            className="group bg-bg-secondary border border-border rounded-[12px] md:rounded-[16px] overflow-hidden hover:-translate-y-1 hover:shadow-md transition-all duration-300 cursor-pointer md:cursor-default relative"
            onClick={() => setActive(active === i ? null : i)}
          >
            <div className="bg-bg-tertiary overflow-hidden">
              <img
                src={image}
                alt={title}
                className="w-full aspect-video object-cover group-hover:scale-105 transition-transform duration-300"
              />
            </div>
            <div className="p-2.5 md:p-7">
              <h3 className="font-heading text-[11px] md:text-lg font-semibold text-text-primary mb-0.5 md:mb-2">{title}</h3>
              <p className="text-text-secondary text-sm leading-relaxed hidden md:block">{desc}</p>
            </div>
            {/* Mobile: tap overlay */}
            {active === i && (
              <div
                className="absolute inset-0 bg-bg-secondary/95 flex items-center justify-center p-3 md:hidden"
                onClick={(e) => { e.stopPropagation(); setActive(null) }}
              >
                <p className="text-text-primary text-[11px] leading-relaxed text-center">{desc}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

export function LandingPage() {
  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-bg-primary/80 backdrop-blur-md border-b border-border/50">
        <div className="flex items-center justify-between px-5 md:px-8 py-3 md:py-4 max-w-6xl mx-auto">
          <a href="/" className="flex items-center gap-2.5">
            <img src="/logo.png" alt="PageFly" className="h-7 w-7 md:h-8 md:w-8 rounded-lg" />
            <span className="font-heading text-base md:text-lg font-bold text-text-primary">PageFly</span>
            <a href="https://x.com/yrzhe_top" target="_blank" rel="noopener noreferrer" className="text-[10px] text-text-tertiary hidden md:inline hover:text-accent-secondary transition-colors">by <span className="text-accent-secondary">yrzhe</span></a>
          </a>
          <div className="flex items-center gap-2">
            <a href="https://github.com/Yrzhe/pagefly" target="_blank" rel="noopener noreferrer" className="text-[9px] md:text-[10px] font-mono text-text-tertiary border border-border px-1.5 py-0.5 rounded hover:text-accent-secondary hover:border-accent-secondary transition-colors">MIT</a>
            <span className="text-[10px] md:text-xs font-medium text-accent-secondary bg-bg-tertiary px-2.5 py-1 md:px-3 md:py-1.5 rounded-full">
              Personal Knowledge OS
            </span>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="relative min-h-[50vh] md:min-h-[70vh] flex items-center justify-center">
          <video
            autoPlay
            muted
            loop
            playsInline
            className="absolute inset-0 w-full h-full object-cover"
            poster="/hero-poster.png"
          >
            <source src="/hero.mp4" type="video/mp4" />
          </video>
          <div className="absolute inset-0 bg-bg-primary/50" />
          <div className="absolute bottom-0 left-0 right-0 h-32 md:h-48 bg-gradient-to-t from-bg-primary to-transparent" />

          <div className="relative z-10 text-center px-5 md:px-8 py-12 md:py-24 max-w-3xl">
            <h1 className="font-heading text-[32px] md:text-[44px] lg:text-[56px] font-bold text-text-primary leading-[1.1] mb-4 md:mb-6">
              Build your personal<br />knowledge OS.
            </h1>
            <p className="text-text-secondary text-sm md:text-lg leading-relaxed max-w-2xl mx-auto mb-6 md:mb-10">
              PageFly is a private knowledge data-set — a structured, automated, API-ready knowledge
              governance system with warm, opinionated architecture.
            </p>
            <div className="flex items-center justify-center gap-3 flex-wrap">
              <a
                href="https://github.com/Yrzhe/pagefly"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 md:gap-2.5 bg-accent-primary text-bg-primary px-5 md:px-7 py-3 md:py-3.5 rounded-[12px] font-semibold text-sm hover:bg-accent-secondary transition-colors shadow-md"
              >
                <GithubIcon size={18} />
                View on GitHub
              </a>
              <a
                href="https://x.com/yrzhe_top/status/2039944530988847617"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 border border-border bg-bg-primary/80 text-text-primary px-5 md:px-7 py-3 md:py-3.5 rounded-[12px] font-semibold text-sm hover:bg-bg-secondary transition-colors shadow-sm"
              >
                <svg width={16} height={16} viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                The Story
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Tagline */}
      <section className="max-w-3xl mx-auto px-5 md:px-8 py-14 md:py-28 text-center">
        <h2 className="font-heading text-xl md:text-[28px] font-semibold text-text-primary leading-snug">
          A warm, structured surface for turning messy notes into durable knowledge.
        </h2>
      </section>

      {/* Features Grid */}
      <FeatureGrid />

      {/* Architecture Pipeline */}
      <section className="bg-bg-secondary border-y border-border">
        <div className="max-w-4xl mx-auto px-5 md:px-8 py-14 md:py-24 text-center">
          <h2 className="font-heading text-xl md:text-[28px] font-semibold text-text-primary mb-3 md:mb-4">
            A visual pipeline from raw notes to usable knowledge.
          </h2>
          <div className="mt-6 md:mt-10 max-w-xl mx-auto rounded-[12px] md:rounded-[16px] overflow-hidden shadow-sm">
            <img
              src="/assets/architecture.png"
              alt="PageFly Architecture"
              className="w-full"
            />
          </div>
        </div>
      </section>

      {/* Inspired By */}
      <section className="max-w-4xl mx-auto px-5 md:px-8 py-14 md:py-28">
        <div className="bg-bg-secondary border border-border rounded-[16px] md:rounded-[20px] p-6 md:p-12 flex flex-col md:flex-row gap-6 md:gap-10 items-center">
          <div className="flex-1">
            <p className="text-[10px] md:text-xs font-semibold uppercase tracking-[1.5px] text-accent-secondary mb-2 md:mb-3">
              Inspired by
            </p>
            <h3 className="font-heading text-lg md:text-2xl font-semibold text-text-primary mb-3 md:mb-4 leading-snug">
              LLMWiki showed what happens when knowledge becomes navigable.
            </h3>
            <p className="text-text-secondary text-sm md:text-[15px] leading-relaxed mb-5">
              Andrej Karpathy's LLMWiki demonstrated the power of structured knowledge compilation.
              PageFly extends that vision with a complete capture-to-serve pipeline, adding ingestion,
              distillation, governance, and API access on top of the wiki model.
            </p>
            <a
              href="https://x.com/yrzhe_top/status/2039944530988847617"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm font-medium text-accent-secondary hover:text-accent-primary transition-colors"
            >
              <svg width={16} height={16} viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
              See the tweet that started it
            </a>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-bg-tertiary/50">
        <div className="max-w-4xl mx-auto px-5 md:px-8 py-14 md:py-24 text-center">
          <h2 className="font-heading text-xl md:text-[28px] font-semibold text-text-primary mb-2 md:mb-3">
            Start building your knowledge OS.
          </h2>
          <p className="text-text-secondary text-sm mb-6 md:mb-8">
            Self-hosted, open-source, yours forever.
          </p>
          <a
            href="https://github.com/Yrzhe/pagefly"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2.5 bg-text-primary text-bg-primary px-6 md:px-7 py-3 md:py-3.5 rounded-[12px] font-semibold text-sm hover:opacity-90 transition-opacity shadow-md"
          >
            <GithubIcon size={18} />
            GitHub
          </a>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-6 md:py-8 px-5 md:px-8">
        <div className="max-w-6xl mx-auto flex items-center justify-between text-xs text-text-tertiary">
          <div className="flex items-center gap-2">
            <a href="https://github.com/Yrzhe/pagefly" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 hover:text-text-secondary transition-colors">
              <img src="/logo.png" alt="" className="h-4 w-4 rounded" />
              <span className="font-heading font-bold text-text-secondary">PageFly</span>
            </a>
            <a href="https://x.com/yrzhe_top" target="_blank" rel="noopener noreferrer" className="hover:text-accent-secondary transition-colors">by <span className="text-accent-secondary">yrzhe</span></a>
          </div>
          <span>&copy; 2026</span>
        </div>
      </footer>
    </div>
  )
}
