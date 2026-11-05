import { useEffect, useState } from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'

interface PageImageProps {
  src: string
  alt: string
  pageNumber: number
  onVisible?: () => void
  onImageClick?: () => void
}

export default function PageImage({
  src,
  alt,
  pageNumber,
  onImageClick,
}: PageImageProps) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [retryCount, setRetryCount] = useState(0)

  // Reset state when image source changes
  useEffect(() => {
    setLoading(true)
    setError(false)
    setRetryCount(0)
  }, [src])

  const handleRetry = (e: React.MouseEvent) => {
    e.stopPropagation()
    setError(false)
    setLoading(true)
    setRetryCount((prev) => prev + 1)
  }

  // Add retry bust query if retrying
  const currentSrc =
    retryCount > 0
      ? src.includes('?')
        ? `${src}&retry=${retryCount}`
        : `${src}?retry=${retryCount}`
      : src

  return (
    <div
      id={`reader-page-${pageNumber}`}
      onClick={onImageClick}
      className="relative w-full max-w-2xl mx-auto min-h-[300px] flex items-center justify-center select-none"
    >
      {/* Loading Skeleton */}
      {loading && !error && (
        <div className="absolute inset-0 bg-surface/50 animate-pulse flex items-center justify-center rounded-lg min-h-[400px]">
          <span className="text-xs font-mono text-text-secondary/50">
            Стр. {pageNumber}
          </span>
        </div>
      )}

      {/* Error Fallback */}
      {error && (
        <div className="w-full min-h-[350px] bg-surface/80 rounded-xl border border-white/5 flex flex-col items-center justify-center p-6 text-center">
          <AlertCircle size={32} className="text-rose-400 mb-2 opacity-80" />
          <p className="text-xs font-medium text-text-primary mb-1">
            Не удалось загрузить страницу {pageNumber}
          </p>
          <p className="text-[11px] text-text-secondary mb-3 max-w-[220px]">
            Проверьте подключение к сети
          </p>
          <button
            onClick={handleRetry}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-white/10 hover:bg-white/15 text-text-primary rounded-lg transition-colors cursor-pointer"
          >
            <RefreshCw size={12} />
            Повторить
          </button>
        </div>
      )}

      {/* Actual Image */}
      {!error && (
        <img
          src={currentSrc}
          alt={alt}
          loading="lazy"
          onLoad={() => setLoading(false)}
          onError={() => {
            setLoading(false)
            setError(true)
          }}
          className={`w-full h-auto object-contain transition-opacity duration-200 ${
            loading ? 'opacity-0' : 'opacity-100'
          }`}
        />
      )}
    </div>
  )
}
