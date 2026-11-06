import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useTelegram } from './hooks/useTelegram'
import { LibraryProvider } from './context/LibraryContext'
import MainLayout from './layouts/MainLayout'

const HomePage = lazy(() => import('./pages/HomePage'))
const SearchPage = lazy(() => import('./pages/SearchPage'))
const MangaDetailPage = lazy(() => import('./pages/MangaDetailPage'))
const ReaderPage = lazy(() => import('./pages/ReaderPage'))
const LibraryPage = lazy(() => import('./pages/LibraryPage'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

function PageLoading() {
  return (
    <div className="flex items-center justify-center min-h-[50vh]">
      <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

function App() {
  // Initialize Telegram WebApp integration (ready, expand, viewport, safe-area sync)
  useTelegram()

  return (
    <BrowserRouter>
      <LibraryProvider>
        <MainLayout>
          <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/manga/:idOrSlug" element={<MangaDetailPage />} />
              <Route path="/manga/:idOrSlug/chapter/:chapterId" element={<ReaderPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </Suspense>
        </MainLayout>
      </LibraryProvider>
    </BrowserRouter>
  )
}

export default App
