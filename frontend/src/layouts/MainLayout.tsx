import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import BottomNav from '../components/BottomNav'

interface MainLayoutProps {
  children: ReactNode
}

export default function MainLayout({ children }: MainLayoutProps) {
  const location = useLocation()
  const isReaderPage = location.pathname.includes('/chapter/')

  return (
    <div
      className="flex flex-col bg-bg h-screen overflow-hidden"
      style={{
        height: 'var(--app-height, 100dvh)',
        maxHeight: 'var(--app-height, 100dvh)',
      }}
    >
      {/* Main content area */}
      <main
        className="flex-1 overflow-y-auto overscroll-contain"
        style={{
          paddingTop: isReaderPage ? '0px' : 'var(--safe-top)',
          paddingBottom: isReaderPage
            ? 'var(--safe-bottom)'
            : 'calc(4.5rem + var(--safe-bottom))',
          paddingLeft: isReaderPage ? '0px' : 'var(--safe-left)',
          paddingRight: isReaderPage ? '0px' : 'var(--safe-right)',
        }}
      >
        {children}
      </main>

      {/* Bottom navigation (hidden in reader mode) */}
      {!isReaderPage && <BottomNav />}
    </div>
  )
}
