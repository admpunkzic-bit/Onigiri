import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Columns,
  Rows,
} from 'lucide-react'

interface ReaderToolbarProps {
  visible: boolean
  mangaTitle: string
  chapterNumber?: number | null
  chapterTitle?: string | null
  currentPage: number
  totalPages: number
  readingMode: 'vertical' | 'paged'
  prevChapterId?: number | null
  nextChapterId?: number | null
  onBack: () => void
  onToggleMode: () => void
  onPrevChapter?: () => void
  onNextChapter?: () => void
  onPageSelect?: (page: number) => void
  onInteractionStart?: () => void
  onInteractionEnd?: () => void
}

export default function ReaderToolbar({
  visible,
  mangaTitle,
  chapterNumber,
  chapterTitle,
  currentPage,
  totalPages,
  readingMode,
  prevChapterId,
  nextChapterId,
  onBack,
  onToggleMode,
  onPrevChapter,
  onNextChapter,
  onInteractionStart,
  onInteractionEnd,
}: ReaderToolbarProps) {
  const hasChapterNum = chapterNumber !== null && chapterNumber !== undefined
  const formattedNumber = hasChapterNum ? String(chapterNumber) : null
  const headerHeading = formattedNumber !== null
    ? `Глава ${formattedNumber}${chapterTitle ? ` — ${chapterTitle}` : ''}`
    : (chapterTitle || 'Чтение')

  return (
    <>
      {/* Top Bar */}
      <header
        onMouseEnter={onInteractionStart}
        onMouseLeave={onInteractionEnd}
        onTouchStart={onInteractionStart}
        onTouchEnd={onInteractionEnd}
        className={`fixed top-0 left-0 right-0 z-40 bg-surface/90 backdrop-blur-md border-b border-white/5 transition-transform duration-200 select-none ${
          visible ? 'translate-y-0' : '-translate-y-full pointer-events-none'
        }`}
        style={{ paddingTop: 'var(--safe-top)' }}
      >
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={(e) => {
                e.stopPropagation()
                onBack()
              }}
              className="p-1.5 text-text-secondary hover:text-text-primary transition-colors cursor-pointer rounded-lg hover:bg-white/5"
              title="Назад к манге"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="min-w-0">
              <h1 className="text-xs font-semibold text-text-primary truncate">
                {headerHeading}
              </h1>
              <p className="text-[10px] text-text-secondary truncate">
                {mangaTitle}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation()
                onToggleMode()
              }}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-white/5 hover:bg-white/10 rounded-xl border border-white/5 transition-colors cursor-pointer"
              title="Переключить режим чтения"
            >
              {readingMode === 'vertical' ? (
                <>
                  <Columns size={13} className="text-accent" />
                  <span>Постраничный</span>
                </>
              ) : (
                <>
                  <Rows size={13} className="text-accent" />
                  <span>Свиток</span>
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Bottom Bar */}
      <footer
        onMouseEnter={onInteractionStart}
        onMouseLeave={onInteractionEnd}
        onTouchStart={onInteractionStart}
        onTouchEnd={onInteractionEnd}
        className={`fixed bottom-0 left-0 right-0 z-40 bg-surface/90 backdrop-blur-md border-t border-white/5 transition-transform duration-200 select-none ${
          visible ? 'translate-y-0' : 'translate-y-full pointer-events-none'
        }`}
        style={{ paddingBottom: 'var(--safe-bottom)' }}
      >
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center justify-between">
          {/* Prev Chapter */}
          <button
            onClick={(e) => {
              e.stopPropagation()
              onPrevChapter?.()
            }}
            disabled={!prevChapterId}
            className="inline-flex items-center gap-1 text-xs font-medium text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:pointer-events-none transition-colors cursor-pointer px-2 py-1 rounded-lg"
          >
            <ChevronLeft size={16} />
            <span>Пред. глава</span>
          </button>

          {/* Page Counter */}
          <div className="text-xs font-mono font-medium text-text-primary bg-white/5 px-3 py-1 rounded-full border border-white/5">
            {currentPage} / {totalPages}
          </div>

          {/* Next Chapter */}
          <button
            onClick={(e) => {
              e.stopPropagation()
              onNextChapter?.()
            }}
            disabled={!nextChapterId}
            className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:text-accent-secondary disabled:opacity-30 disabled:pointer-events-none transition-colors cursor-pointer px-2 py-1 rounded-lg"
          >
            <span>След. глава</span>
            <ChevronRight size={16} />
          </button>
        </div>
      </footer>
    </>
  )
}
