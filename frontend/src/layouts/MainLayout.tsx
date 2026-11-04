import type { ReactNode } from 'react'
import BottomNav from '../components/BottomNav'

interface MainLayoutProps {
  children: ReactNode
}

export default function MainLayout({ children }: MainLayoutProps) {
  return (
    <div
      className="flex flex-col bg-bg min-h-screen"
      style={{ minHeight: 'var(--app-height, 100dvh)' }}
    >
      {/* Main content area */}
      <main
        className="flex-1 overflow-y-auto"
        style={{
          paddingTop: 'var(--safe-top)',
          paddingBottom: 'calc(4.5rem + var(--safe-bottom))',
          paddingLeft: 'var(--safe-left)',
          paddingRight: 'var(--safe-right)',
        }}
      >
        {children}
      </main>

      {/* Bottom navigation */}
      <BottomNav />
    </div>
  )
}
