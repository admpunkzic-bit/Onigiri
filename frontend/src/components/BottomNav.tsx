import { Home, Search, BookOpen, User } from 'lucide-react'
import { useState } from 'react'

const navItems = [
  { icon: Home, label: 'Главная', id: 'home' },
  { icon: Search, label: 'Поиск', id: 'search' },
  { icon: BookOpen, label: 'Библиотека', id: 'library' },
  { icon: User, label: 'Профиль', id: 'profile' },
] as const

export default function BottomNav() {
  const [active, setActive] = useState('home')

  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-surface border-t border-white/5 px-2 py-2 z-50">
      <div className="flex justify-around items-center max-w-md mx-auto">
        {navItems.map(({ icon: Icon, label, id }) => {
          const isActive = active === id
          return (
            <button
              key={id}
              onClick={() => setActive(id)}
              className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded-lg transition-colors ${
                isActive
                  ? 'text-accent'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Icon size={22} strokeWidth={isActive ? 2.5 : 2} />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
