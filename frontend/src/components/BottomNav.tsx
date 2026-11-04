import { Home, Search, BookOpen, Clock, Settings } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

const navItems = [
  { icon: Home, label: 'Главная', path: '/' },
  { icon: Search, label: 'Поиск', path: '/search' },
  { icon: BookOpen, label: 'Библиотека', path: '/library' },
  { icon: Clock, label: 'История', path: '/history' },
  { icon: Settings, label: 'Настройки', path: '/settings' },
] as const

export default function BottomNav() {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 bg-surface border-t border-white/5 px-2 pt-2 z-50"
      style={{
        paddingBottom: 'calc(0.5rem + var(--safe-bottom))',
        paddingLeft: 'var(--safe-left)',
        paddingRight: 'var(--safe-right)',
      }}
    >
      <div className="flex justify-around items-center max-w-md mx-auto">
        {navItems.map(({ icon: Icon, label, path }) => {
          const isActive = location.pathname === path
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded-lg transition-colors ${
                isActive
                  ? 'text-accent'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
