import { useEffect, useLayoutEffect, useRef } from 'react'
import { ChevronRight } from 'lucide-react'
import type { ChapterReaderPageItem } from '../../types/manga'
import PageImage from './PageImage'

interface VerticalReaderProps {
  pages: ChapterReaderPageItem[]
  currentPage: number
  onPageChange: (pageNumber: number) => void
  onToggleControls: () => void
  nextChapterId?: number | null
  onNextChapter?: () => void
}

export default function VerticalReader({
  pages,
  currentPage,
  onPageChange,
  onToggleControls,
  nextChapterId,
  onNextChapter,
}: VerticalReaderProps) {
  const isInitialScrollDone = useRef(false)

  // Scroll to active page on initial mount (e.g. when switching from Paged mode)
  useLayoutEffect(() => {
    if (isInitialScrollDone.current) return
    isInitialScrollDone.current = true

    if (currentPage > 1) {
      // Small timeout to allow images DOM elements to render in layout
      setTimeout(() => {
        const el = document.getElementById(`reader-page-${currentPage}`)
        if (el) {
          el.scrollIntoView({ behavior: 'auto', block: 'start' })
        }
      }, 50)
    }
  }, [currentPage])

  // Track active visible page via IntersectionObserver
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const pageId = entry.target.id
            const match = pageId.match(/^reader-page-(\d+)$/)
            if (match) {
              const num = parseInt(match[1], 10)
              if (!isNaN(num)) {
                onPageChange(num)
              }
            }
          }
        }
      },
      {
        rootMargin: '-20% 0px -50% 0px',
        threshold: 0.1,
      }
    )

    pages.forEach((p) => {
      const el = document.getElementById(`reader-page-${p.page_number}`)
      if (el) observer.observe(el)
    })

    return () => observer.disconnect()
  }, [pages, onPageChange])

  return (
    <div className="w-full flex flex-col items-center py-16 px-2 sm:px-0">
      <div className="w-full max-w-2xl space-y-2">
        {pages.map((p) => (
          <PageImage
            key={`${p.page_number}-${p.image_url}`}
            src={p.image_url}
            alt={`Страница ${p.page_number}`}
            pageNumber={p.page_number}
            onImageClick={onToggleControls}
          />
        ))}

        {/* End of chapter card */}
        <div className="py-16 text-center">
          <div className="bg-surface rounded-2xl border border-white/5 p-8 max-w-md mx-auto">
            <h3 className="text-sm font-semibold text-text-primary mb-2">
              Глава завершена
            </h3>
            <p className="text-xs text-text-secondary mb-6">
              Вы прочитали все страницы этой главы.
            </p>

            {nextChapterId ? (
              <button
                onClick={onNextChapter}
                className="w-full inline-flex items-center justify-center gap-2 py-3 px-4 bg-accent hover:bg-accent/90 text-white text-xs font-semibold rounded-xl transition-colors cursor-pointer"
              >
                <span>Следующая глава</span>
                <ChevronRight size={16} />
              </button>
            ) : (
              <p className="text-xs text-accent font-medium">
                Это последняя доступная глава произведения.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
