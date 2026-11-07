import { useState, useRef, useEffect, useMemo } from 'react'
import { Users, ChevronDown, Check, RefreshCw } from 'lucide-react'
import type { TranslationVariant } from '../types/manga'

interface TranslationSelectorProps {
  translations: TranslationVariant[]
  selectedTranslationId: string | null
  onSelectTranslation: (transId: string) => void
  isLoading?: boolean
}

function getSourceBadge(sourceName: string): string {
  if (sourceName === 'remanga') return 'ReManga'
  if (sourceName === 'mangalib') return 'MangaLib'
  return sourceName
}

function pluralizeChapters(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return 'глава'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'главы'
  return 'глав'
}

export default function TranslationSelector({
  translations,
  selectedTranslationId,
  onSelectTranslation,
  isLoading = false,
}: TranslationSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on click outside and on Escape
  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  const selectedVariant = useMemo(() => {
    return (
      translations.find((t) => t.id === selectedTranslationId) ||
      translations[0] ||
      null
    )
  }, [translations, selectedTranslationId])

  if (!translations || translations.length === 0) {
    return null
  }

  const selectedSourceBadge = selectedVariant
    ? getSourceBadge(selectedVariant.source_name)
    : ''

  return (
    <div ref={containerRef} className="relative mb-4 select-none">
      {/* Compact Trigger Row */}
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className={`w-full flex items-center justify-between gap-2.5 px-3.5 py-2.5 rounded-xl bg-surface/80 hover:bg-surface border transition-all cursor-pointer text-left ${
          isOpen
            ? 'border-accent/50 bg-surface shadow-sm ring-1 ring-accent/20'
            : 'border-white/5 hover:border-white/10'
        }`}
      >
        {/* Left: Icon, Translator, Source badge, Chapters count */}
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Users size={14} className="shrink-0 text-accent" />
          <span className="text-[11px] font-medium text-text-secondary uppercase tracking-wider shrink-0 hidden xs:inline">
            Перевод:
          </span>
          <span className="text-xs font-semibold text-text-primary truncate">
            {selectedVariant?.translator_name || 'Неизвестный'}
          </span>
          {selectedSourceBadge && (
            <span className="shrink-0 text-[10px] text-text-secondary bg-white/5 px-2 py-0.5 rounded-full border border-white/5">
              {selectedSourceBadge}
            </span>
          )}
          {selectedVariant && (
            <span className="shrink-0 text-[11px] text-text-secondary font-medium">
              {selectedVariant.chapters_count}{' '}
              {pluralizeChapters(selectedVariant.chapters_count)}
            </span>
          )}
          {selectedVariant?.has_gaps && (
            <span className="shrink-0 text-[10px] text-amber-400/90 hidden sm:inline">
              (пропуски)
            </span>
          )}
        </div>

        {/* Right: Loading spinner, variant count pill, Chevron arrow */}
        <div className="flex items-center gap-1.5 shrink-0">
          {isLoading && (
            <RefreshCw size={12} className="animate-spin text-accent shrink-0" />
          )}
          {translations.length > 1 && (
            <span className="text-[10px] text-text-secondary bg-white/5 px-1.5 py-0.5 rounded border border-white/5 hidden sm:inline">
              {translations.length}{' '}
              {translations.length < 5 ? 'вар.' : 'вар.'}
            </span>
          )}
          <ChevronDown
            size={15}
            className={`text-text-secondary transition-transform duration-200 shrink-0 ${
              isOpen ? 'rotate-180 text-accent' : ''
            }`}
          />
        </div>
      </button>

      {/* Expanded Menu Dropdown */}
      {isOpen && (
        <div
          role="listbox"
          className="absolute left-0 right-0 top-full mt-1.5 z-30 bg-surface/95 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl p-1.5 space-y-1 max-h-64 sm:max-h-72 overflow-y-auto"
        >
          <div className="px-2.5 py-1 flex items-center justify-between text-[11px] text-text-secondary border-b border-white/5 mb-1">
            <span className="font-medium">Доступные переводы</span>
            <span>
              {translations.length}{' '}
              {translations.length === 1
                ? 'вариант'
                : translations.length < 5
                  ? 'варианта'
                  : 'вариантов'}
            </span>
          </div>

          {translations.map((t) => {
            const isSelected = t.id === selectedTranslationId
            const sourceBadge = getSourceBadge(t.source_name)

            return (
              <button
                key={t.id}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => {
                  onSelectTranslation(t.id)
                  setIsOpen(false)
                }}
                disabled={isLoading}
                className={`w-full text-left p-2.5 rounded-lg border transition-all cursor-pointer flex items-center justify-between gap-2 ${
                  isSelected
                    ? 'bg-accent/15 border-accent/60 shadow-sm'
                    : 'bg-surface/50 border-white/5 hover:border-accent/30 hover:bg-white/5'
                } ${isLoading ? 'opacity-60 cursor-not-allowed' : ''}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap mb-1">
                    <span
                      className={`text-xs font-semibold truncate ${
                        isSelected ? 'text-accent' : 'text-text-primary'
                      }`}
                    >
                      {t.translator_name}
                    </span>
                    <span className="text-[10px] text-text-secondary bg-white/5 px-2 py-0.5 rounded-full border border-white/5 shrink-0">
                      {sourceBadge}
                    </span>
                    {t.is_default && (
                      <span className="text-[9px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20 font-medium shrink-0">
                        Основной
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-text-secondary flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="font-medium text-text-primary/90">
                      {t.chapters_count} {pluralizeChapters(t.chapters_count)}
                    </span>
                    {t.volumes_count > 0 && (
                      <>
                        <span>•</span>
                        <span>
                          {t.volumes_count}{' '}
                          {t.volumes_count === 1
                            ? 'том'
                            : t.volumes_count < 5
                              ? 'тома'
                              : 'томов'}
                        </span>
                      </>
                    )}
                    {t.min_chapter !== null && t.max_chapter !== null && (
                      <>
                        <span>•</span>
                        <span>
                          главы {t.min_chapter}–{t.max_chapter}
                        </span>
                      </>
                    )}
                    {t.has_gaps && (
                      <span className="text-amber-400/90 text-[10px]">
                        (есть пропуски: {t.gaps_count})
                      </span>
                    )}
                  </div>
                </div>

                <div className="shrink-0 flex items-center pl-2">
                  {isSelected ? (
                    <div className="w-5 h-5 rounded-full bg-accent flex items-center justify-center text-white">
                      <Check size={12} strokeWidth={3} />
                    </div>
                  ) : (
                    <div className="w-5 h-5 rounded-full border border-white/20" />
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

