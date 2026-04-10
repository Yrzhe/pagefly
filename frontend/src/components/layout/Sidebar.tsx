import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  BookOpen,
  Globe,
  FolderOpen,
  GitFork,
  Key,
  Search,
  Settings,
  MessageCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { to: '/wiki', label: 'Wiki', icon: Globe },
  { to: '/workspace', label: 'Workspace', icon: FolderOpen },
  { to: '/graph', label: 'Graph', icon: GitFork },
  { to: '/api', label: 'API', icon: Key },
  { to: '/chat', label: 'Chat', icon: MessageCircle },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/settings', label: 'Settings', icon: Settings },
] as const

export function Sidebar() {
  return (
    <aside className="flex flex-col w-[180px] min-h-screen bg-sidebar-bg border-r border-border">
      <div className="px-5 py-6">
        <span className="font-heading text-lg font-bold text-text-primary tracking-tight">
          PageFly
        </span>
      </div>

      <nav className="flex-1 flex flex-col gap-0.5 px-3">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'text-accent-primary bg-bg-tertiary border-l-2 border-accent-primary font-medium'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
              )
            }
          >
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
