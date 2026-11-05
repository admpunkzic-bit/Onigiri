import { useEffect, useRef } from 'react'
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
}: PagedReaderProps) {
  const touchStartX = useRef<number | null>(null)
  const touchStartY = useRef<number | null>(null)

  const activePage = pages.find((p) => p.page_number === currentPage) || pages[0]

  // Preload next page
  useEffect(() => {
    if (currentPage < pages.length) {
      const nextPage = pages.find((p) => p.page_number === currentPage + 1)
      if (nextPage) {
        const img = new Image()
        img.src = nextPage.image_url
      }
    }
  }, [currentPage, pages])

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
      onNextChapter()
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
    const widthRatio = clickX / rect.width

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
    </div>
  )
}
