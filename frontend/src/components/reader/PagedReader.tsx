import { useEffect, useRef } from 'react'
import { ChevronRight } from 'lucide-react'
import type { ChapterReaderPageItem } from '../../types/manga'
import PageImage from './PageImage'

interface PagedReaderProps {
  pages: ChapterReaderPageItem[]
  currentPage: number
  onPageChange: (pageNumber: number) => void
  onToggleControls: () => void
  nextChapterId?: number | null
  onNextChapter?: () => void
  prevChapterId?: number | null
  onPrevChapter?: () => void
  preloadPages?: boolean
  autoNextChapter?: boolean
}

export default function PagedReader({
  pages,
  currentPage,
  onPageChange,
  onToggleControls,
  nextChapterId,
  onNextChapter,
  prevChapterId,
  onPrevChapter,
  preloadPages = true,
  autoNextChapter = true,
}: PagedReaderProps) {
  const touchStartX = useRef<number | null>(null)
  const touchStartY = useRef<number | null>(null)

  const activePage = pages.find((p) => p.page_number === currentPage) || pages[0]

  // Preload next 2 pages if preloadPages setting is enabled
  useEffect(() => {
    if (!preloadPages) return
    for (let offset = 1; offset <= 2; offset++) {
      const targetPageNum = currentPage + offset
      if (targetPageNum <= pages.length) {
        const nextPage = pages.find((p) => p.page_number === targetPageNum)
        if (nextPage) {
          const img = new Image()
          img.src = nextPage.image_url
        }
      }
    }
  }, [currentPage, pages, preloadPages])

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === ' ') {
        e.preventDefault()
        handleNext()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        handlePrev()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [currentPage, pages.length])

  const handlePrev = () => {
    if (currentPage > 1) {
      onPageChange(currentPage - 1)
    } else if (prevChapterId && onPrevChapter) {
      onPrevChapter()
    }
  }

  const handleNext = () => {
    if (currentPage < pages.length) {
      onPageChange(currentPage + 1)
    } else if (nextChapterId && onNextChapter) {
      if (autoNextChapter) {
        onNextChapter()
      }
    }
  }

  // Swipe handling
  const handleTouchStart = (e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX
    touchStartY.current = e.touches[0].clientY
  }

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (touchStartX.current === null || touchStartY.current === null) return
    const deltaX = e.changedTouches[0].clientX - touchStartX.current
    const deltaY = e.changedTouches[0].clientY - touchStartY.current

    // Only trigger horizontal swipe if deltaX > deltaY (avoid vertical scrolling conflict)
    if (Math.abs(deltaX) > 50 && Math.abs(deltaX) > Math.abs(deltaY)) {
      if (deltaX > 0) {
        handlePrev()
      } else {
        handleNext()
      }
    }

    touchStartX.current = null
    touchStartY.current = null
  }

  const handleZoneClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const clickY = e.clientY - rect.top
    const widthRatio = clickX / rect.width
    const heightRatio = clickY / rect.height

    // Tapping top 20% of the screen always toggles/restores controls
    if (heightRatio < 0.2) {
      onToggleControls()
      return
    }

    if (widthRatio < 0.3) {
      handlePrev()
    } else if (widthRatio > 0.7) {
      handleNext()
    } else {
      onToggleControls()
    }
  }

  if (!activePage) return null

  return (
    <div
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onClick={handleZoneClick}
      className="relative w-full min-h-[calc(100dvh-5rem)] flex items-center justify-center select-none py-14 px-2"
    >
      <div className="w-full max-w-2xl mx-auto flex items-center justify-center">
        <PageImage
          key={`${activePage.page_number}-${activePage.image_url}`}
          src={activePage.image_url}
          alt={`Страница ${activePage.page_number}`}
          pageNumber={activePage.page_number}
        />
      </div>

      {/* Visual tap hint zones indicator on hover/desktop */}
      <div className="absolute inset-y-0 left-0 w-[30%] cursor-w-resize" title="Предыдущая страница" />
      <div className="absolute inset-y-0 right-0 w-[30%] cursor-e-resize" title="Следующая страница" />

      {/* Manual transition button when autoNextChapter is disabled */}
      {!autoNextChapter && currentPage === pages.length && nextChapterId && onNextChapter && (
        <div className="absolute bottom-20 left-1/2 -translate-x-1/2 z-20">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onNextChapter()
            }}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent text-white text-xs font-semibold shadow-lg shadow-accent/25 hover:bg-accent/90 transition-all active:scale-95 cursor-pointer"
          >
            <span>Следующая глава</span>
            <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
