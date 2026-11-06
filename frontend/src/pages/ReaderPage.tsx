import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { AlertCircle, RefreshCw } from 'lucide-react'
import {
  fetchChapterPages,
  fetchReadingProgress,
  saveReadingProgress,
} from '../services/api'
import type { ChapterReaderDetail } from '../types/manga'
import PagedReader from '../components/reader/PagedReader'
import ReaderToolbar from '../components/reader/ReaderToolbar'
import VerticalReader from '../components/reader/VerticalReader'

export default function ReaderPage() {
  const { idOrSlug, chapterId } = useParams<{ idOrSlug: string; chapterId: string }>()
  const navigate = useNavigate()
  const location = useLocation()

  const [detail, setDetail] = useState<ChapterReaderDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState<number>(1)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [reloadKey, setReloadKey] = useState<number>(0)

  // Mode: 'vertical' (continuous webtoon scroll) or 'paged' (single slide)
  const [readingMode, setReadingMode] = useState<'vertical' | 'paged'>(() => {
    try {
      const saved = localStorage.getItem('onigiri_reader_mode')
      return saved === 'paged' ? 'paged' : 'vertical'
    } catch {
      return 'vertical'
    }
  })

  const saveTimerRef = useRef<number | null>(null)

  // ── Telegram BackButton Integration ────────────────────────
  useEffect(() => {
    const tg = window.Telegram?.WebApp
    const backBtn = tg?.BackButton
    if (backBtn) {
      try {
        backBtn.show()
        const handleBack = () => {
          navigate(`/manga/${idOrSlug}`)
        }
        backBtn.onClick(handleBack)

        return () => {
          backBtn.offClick(handleBack)
          backBtn.hide()
        }
      } catch {
        // Ignore in non-standard environments
      }
    }
  }, [idOrSlug, navigate])

  // ── Load Chapter Details & Restore Progress ────────────────
  useEffect(() => {
    if (!idOrSlug || !chapterId) return

    const chIdNum = parseInt(chapterId, 10)
    if (isNaN(chIdNum)) {
      setError('Некорректный номер главы')
      setLoading(false)
      return
    }

    let isMounted = true
    const abortController = new AbortController()

    setLoading(true)
    setError(null)

    const runLoad = async () => {
      try {
        const locationState = location.state as { initialPage?: number } | null | undefined
        const stateInitialPage =
          typeof locationState?.initialPage === 'number' && locationState.initialPage >= 1
            ? locationState.initialPage
            : null

        if (stateInitialPage !== null) {
          // Fast-path: initial page known from navigation state, fetch chapter pages only
          const data = await fetchChapterPages(idOrSlug, chIdNum, abortController.signal)
          if (!isMounted) return
          const targetPage = Math.min(stateInitialPage, data.total_pages)
          setDetail(data)
          setCurrentPage(targetPage)
        } else {
          // Parallel fetch: retrieve both chapter reader details and user reading progress
          const [data, prog] = await Promise.all([
            fetchChapterPages(idOrSlug, chIdNum, abortController.signal),
            fetchReadingProgress(idOrSlug, abortController.signal).catch((err) => {
              if (err instanceof DOMException && err.name === 'AbortError') {
                throw err
              }
              return null
            }),
          ])

          if (!isMounted) return

          let targetPage = 1
          if (prog && prog.chapter_id === chIdNum && prog.page_number >= 1) {
            targetPage = Math.min(prog.page_number, data.total_pages)
          }

          setDetail(data)
          setCurrentPage(targetPage)
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          // Request aborted on component unmount or navigation change; ignore
          return
        }
        if (isMounted) {
          console.error('Failed to load chapter pages:', err)
          setError('Не удалось загрузить страницы главы. Проверьте подключение к сети.')
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }

    runLoad()

    return () => {
      isMounted = false
      abortController.abort()
    }
  }, [idOrSlug, chapterId, location.state, reloadKey])

  // ── Debounced Progress Auto-Save ───────────────────────────
  useEffect(() => {
    if (!idOrSlug || !detail || loading) return

    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current)
    }

    // Debounce saving progress by 600ms
    saveTimerRef.current = window.setTimeout(() => {
      saveReadingProgress(idOrSlug, {
        chapter_id: detail.chapter_id,
        chapter_number: detail.chapter_number,
        chapter_title: detail.title,
        page_number: currentPage,
        total_pages: detail.total_pages,
      })
    }, 600)

    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current)
      }
    }
  }, [idOrSlug, detail, currentPage, loading])

  // ── Mode Switcher (Seamless: Preserves currentPage) ────────
  const handleToggleMode = () => {
    const nextMode = readingMode === 'vertical' ? 'paged' : 'vertical'
    setReadingMode(nextMode)
    try {
      localStorage.setItem('onigiri_reader_mode', nextMode)
    } catch {
      // Ignore
    }
  }

  // ── Chapter Transitions ────────────────────────────────────
  const handlePrevChapter = () => {
    if (detail?.prev_chapter_id) {
      navigate(`/manga/${idOrSlug}/chapter/${detail.prev_chapter_id}`)
    }
  }

  const handleNextChapter = () => {
    if (detail?.next_chapter_id) {
      navigate(`/manga/${idOrSlug}/chapter/${detail.next_chapter_id}`)
    }
  }

  // ── Loading state ──────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-[#0d0e14] flex flex-col items-center justify-center p-6 text-center select-none">
        <div className="w-12 h-12 rounded-2xl bg-accent/15 text-accent flex items-center justify-center mb-4 animate-spin">
          <RefreshCw size={24} />
        </div>
        <h2 className="text-sm font-semibold text-text-primary mb-1">
          Загрузка главы...
        </h2>
        <p className="text-xs text-text-secondary">
          Получение страниц из безопасного источника
        </p>
      </div>
    )
  }

  // ── Error state ────────────────────────────────────────────
  if (error || !detail) {
    return (
      <div className="min-h-screen bg-[#0d0e14] flex flex-col items-center justify-center p-6 text-center select-none">
        <div className="w-14 h-14 rounded-2xl bg-rose-500/10 text-rose-400 flex items-center justify-center mb-4">
          <AlertCircle size={28} />
        </div>
        <h2 className="text-base font-semibold text-text-primary mb-1">
          Ошибка открытия читалки
        </h2>
        <p className="text-xs text-text-secondary max-w-[280px] mb-6 leading-relaxed">
          {error || 'Не удалось загрузить данные главы.'}
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => navigate(`/manga/${idOrSlug}`)}
            className="px-4 py-2 text-xs font-medium bg-white/10 hover:bg-white/15 text-text-primary rounded-xl transition-colors cursor-pointer"
          >
            Назад к манге
          </button>
          <button
            onClick={() => setReloadKey((k) => k + 1)}
            className="px-4 py-2 text-xs font-medium bg-accent hover:bg-accent/90 text-white rounded-xl transition-colors cursor-pointer"
          >
            Повторить
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0d0e14] text-text-primary select-none overflow-x-hidden">
      {/* Top and Bottom Controls */}
      <ReaderToolbar
        visible={controlsVisible}
        mangaTitle={detail.manga_title}
        chapterNumber={detail.chapter_number}
        chapterTitle={detail.title}
        currentPage={currentPage}
        totalPages={detail.total_pages}
        readingMode={readingMode}
        prevChapterId={detail.prev_chapter_id}
        nextChapterId={detail.next_chapter_id}
        onBack={() => navigate(`/manga/${idOrSlug}`)}
        onToggleMode={handleToggleMode}
        onPrevChapter={handlePrevChapter}
        onNextChapter={handleNextChapter}
        onPageSelect={(p) => setCurrentPage(p)}
      />

      {/* Reader Body: Vertical vs Paged */}
      <main className="w-full">
        {readingMode === 'vertical' ? (
          <VerticalReader
            pages={detail.pages}
            currentPage={currentPage}
            onPageChange={(page) => setCurrentPage(page)}
            onToggleControls={() => setControlsVisible(!controlsVisible)}
            nextChapterId={detail.next_chapter_id}
            onNextChapter={handleNextChapter}
          />
        ) : (
          <PagedReader
            pages={detail.pages}
            currentPage={currentPage}
            onPageChange={(page) => setCurrentPage(page)}
            onToggleControls={() => setControlsVisible(!controlsVisible)}
            nextChapterId={detail.next_chapter_id}
            onNextChapter={handleNextChapter}
            prevChapterId={detail.prev_chapter_id}
            onPrevChapter={handlePrevChapter}
          />
        )}
      </main>
    </div>
  )
}
