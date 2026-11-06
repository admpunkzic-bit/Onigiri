import { useEffect, useState } from 'react'
import {
  BookOpen,
  Check,
  Database,
  RotateCcw,
  Scroll,
  Trash2,
} from 'lucide-react'
import { useSettings } from '../context/SettingsContext'

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean
  onChange: (val: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
        checked ? 'bg-accent' : 'bg-white/10'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
          checked ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  )
}

function calculateStorageStats(): {
  totalBytes: number
  itemsCount: number
  formattedSize: string
  details: { key: string; sizeBytes: number }[]
} {
  if (typeof window === 'undefined') {
    return { totalBytes: 0, itemsCount: 0, formattedSize: '0 КБ', details: [] }
  }
  let totalBytes = 0
  let itemsCount = 0
  const details: { key: string; sizeBytes: number }[] = []

  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && key.startsWith('onigiri_')) {
        const val = localStorage.getItem(key) || ''
        const sizeBytes = (key.length + val.length) * 2 // UTF-16 characters: 2 bytes each
        totalBytes += sizeBytes
        itemsCount++
        details.push({ key, sizeBytes })
      }
    }
  } catch {
    // Ignore storage errors
  }

  let formattedSize = '0 КБ'
  if (totalBytes < 1024) {
    formattedSize = `${totalBytes} Б`
  } else if (totalBytes < 1024 * 1024) {
    formattedSize = `${(totalBytes / 1024).toFixed(1)} КБ`
  } else {
    formattedSize = `${(totalBytes / (1024 * 1024)).toFixed(2)} МБ`
  }

  return { totalBytes, itemsCount, formattedSize, details }
}

export default function SettingsPage() {
  const { settings, updateSettings, resetSettings } = useSettings()

  const [storageStats, setStorageStats] = useState(calculateStorageStats)
  const [isClearModalOpen, setIsClearModalOpen] = useState(false)
  const [isResetModalOpen, setIsResetModalOpen] = useState(false)
  const [showToast, setShowToast] = useState<string | null>(null)

  useEffect(() => {
    setStorageStats(calculateStorageStats())
  }, [settings])

  const triggerToast = (msg: string) => {
    setShowToast(msg)
    setTimeout(() => setShowToast(null), 3000)
  }

  const handleClearCache = async () => {
    try {
      // 1. Remove search query cache
      localStorage.removeItem('onigiri_recent_search_v1')

      // 2. Remove any browser CacheStorage if registered
      if (typeof window !== 'undefined' && 'caches' in window) {
        const cacheKeys = await window.caches.keys()
        await Promise.all(cacheKeys.map((k) => window.caches.delete(k)))
      }

      setStorageStats(calculateStorageStats())
      setIsClearModalOpen(false)
      triggerToast('Кеш поиска успешно очищен')
    } catch (err) {
      console.error('Failed to clear cache:', err)
      triggerToast('Ошибка при очистке кеша')
    }
  }

  const handleResetSettings = () => {
    resetSettings()
    setIsResetModalOpen(false)
    triggerToast('Настройки сброшены по умолчанию')
  }

  return (
    <div className="px-4 pt-6 pb-24 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-xl font-bold text-text-primary">Настройки</h1>
        <p className="text-xs text-text-secondary mt-0.5">
          Параметры читалки и интерфейса Onigiri
        </p>
      </header>

      {/* Toast Notification */}
      {showToast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent text-white text-xs font-medium shadow-xl shadow-accent/20 animate-in fade-in slide-in-from-top-2">
          <Check size={15} />
          <span>{showToast}</span>
        </div>
      )}

      {/* Section 1: Читалка */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider px-1">
          Читалка
        </h2>

        {/* Режим по умолчанию */}
        <div className="bg-surface rounded-xl p-4 border border-white/5 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-text-primary">
                Режим чтения по умолчанию
              </p>
              <p className="text-xs text-text-secondary mt-0.5">
                Определяет способ отображения страниц при открытии новой главы
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 pt-1">
            <button
              type="button"
              onClick={() => updateSettings({ defaultReadingMode: 'vertical' })}
              className={`flex items-center justify-center gap-2 py-2.5 px-3 rounded-lg border text-xs font-medium transition-all cursor-pointer ${
                settings.defaultReadingMode === 'vertical'
                  ? 'bg-accent/15 border-accent text-accent'
                  : 'bg-white/5 border-transparent text-text-secondary hover:text-text-primary hover:bg-white/10'
              }`}
            >
              <Scroll size={16} />
              <span>Вертикальный (лента)</span>
            </button>

            <button
              type="button"
              onClick={() => updateSettings({ defaultReadingMode: 'paged' })}
              className={`flex items-center justify-center gap-2 py-2.5 px-3 rounded-lg border text-xs font-medium transition-all cursor-pointer ${
                settings.defaultReadingMode === 'paged'
                  ? 'bg-accent/15 border-accent text-accent'
                  : 'bg-white/5 border-transparent text-text-secondary hover:text-text-primary hover:bg-white/10'
              }`}
            >
              <BookOpen size={16} />
              <span>Постраничный (слайды)</span>
            </button>
          </div>
        </div>

        {/* Запоминать последний режим */}
        <div className="flex items-center justify-between gap-4 py-3.5 px-4 bg-surface rounded-xl border border-white/5">
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary">
              Запоминать режим чтения
            </p>
            <p className="text-xs text-text-secondary mt-0.5">
              Автоматически сохранять режим, переключённый во время чтения
            </p>
          </div>
          <Toggle
            checked={settings.rememberLastMode}
            onChange={(val) => updateSettings({ rememberLastMode: val })}
          />
        </div>

        {/* Автопереход к следующей главе */}
        <div className="flex items-center justify-between gap-4 py-3.5 px-4 bg-surface rounded-xl border border-white/5">
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary">
              Автопереход к следующей главе
            </p>
            <p className="text-xs text-text-secondary mt-0.5">
              Переходить к следующей главе при завершении текущей
            </p>
          </div>
          <Toggle
            checked={settings.autoNextChapter}
            onChange={(val) => updateSettings({ autoNextChapter: val })}
          />
        </div>

        {/* Предзагрузка страниц */}
        <div className="flex items-center justify-between gap-4 py-3.5 px-4 bg-surface rounded-xl border border-white/5">
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary">
              Предзагрузка страниц
            </p>
            <p className="text-xs text-text-secondary mt-0.5">
              Загружать следующие страницы в фоне для непрерывного чтения без ожидания
            </p>
          </div>
          <Toggle
            checked={settings.preloadPages}
            onChange={(val) => updateSettings({ preloadPages: val })}
          />
        </div>
      </section>

      {/* Section 2: Поведение */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider px-1">
          Поведение интерфейса
        </h2>

        {/* Автоскрытие панелей */}
        <div className="flex items-center justify-between gap-4 py-3.5 px-4 bg-surface rounded-xl border border-white/5">
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary">
              Автоскрытие панелей читалки
            </p>
            <p className="text-xs text-text-secondary mt-0.5">
              Скрывать панели управления через 3.5 секунды неактивности
            </p>
          </div>
          <Toggle
            checked={settings.autoHideControls}
            onChange={(val) => updateSettings({ autoHideControls: val })}
          />
        </div>
      </section>

      {/* Section 3: Хранилище */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider px-1">
          Хранилище
        </h2>

        <div className="bg-surface rounded-xl p-4 border border-white/5 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-accent/10 text-accent flex-shrink-0 mt-0.5">
                <Database size={18} />
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">
                  Локальные данные Onigiri
                </p>
                <p className="text-xs text-text-secondary mt-0.5">
                  Фактический размер в хранилище: {storageStats.formattedSize} ({storageStats.itemsCount} ключей)
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setIsClearModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-red-400 hover:bg-red-500/10 border border-white/10 hover:border-red-500/20 transition-all cursor-pointer flex-shrink-0"
              title="Очистить кеш поиска"
            >
              <Trash2 size={13} />
              <span>Очистить кеш</span>
            </button>
          </div>

          <p className="text-[11px] text-text-secondary/70 leading-relaxed border-t border-white/5 pt-2.5">
            Очистка удаляет недавние поисковые запросы и временный кеш изображений браузера, не затрагивая настройки, библиотеку и историю.
          </p>
        </div>
      </section>

      {/* Section 4: Сброс настроек */}
      <section className="pt-1">
        <button
          type="button"
          onClick={() => setIsResetModalOpen(true)}
          className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-text-secondary hover:text-text-primary text-xs font-medium transition-all cursor-pointer"
        >
          <RotateCcw size={14} />
          <span>Сбросить настройки читалки по умолчанию</span>
        </button>
      </section>

      {/* Section 5: О приложении */}
      <section className="pt-4 border-t border-white/5 text-center space-y-1.5">
        <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-text-primary">
          <span>Onigiri Web Reader</span>
          <span className="px-1.5 py-0.5 rounded bg-accent/20 text-accent text-[10px]">v0.14.0</span>
        </div>
        <p className="text-[11px] text-text-secondary">
          Платформа: Telegram WebApp & Modern Web
        </p>
        <p className="text-[11px] text-text-secondary/60">
          Основной источник: Manga-Chan • Резервный: MangaDex
        </p>
      </section>

      {/* Modal: Clear Cache */}
      {isClearModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
          <div className="bg-surface border border-white/10 rounded-2xl p-5 max-w-sm w-full shadow-2xl space-y-4">
            <div className="w-12 h-12 rounded-xl bg-accent/10 flex items-center justify-center text-accent mx-auto">
              <Database size={24} />
            </div>

            <div className="text-center space-y-1">
              <h3 className="text-base font-semibold text-text-primary">
                Очистить кеш поиска?
              </h3>
              <p className="text-xs text-text-secondary leading-relaxed">
                Будут удалены недавние поисковые запросы и временные данные браузера. Настройки и история чтения сохранятся.
              </p>
            </div>

            <div className="flex gap-2.5 pt-1">
              <button
                type="button"
                onClick={() => setIsClearModalOpen(false)}
                className="flex-1 py-2.5 px-4 rounded-xl border border-white/10 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-white/5 transition-colors cursor-pointer"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleClearCache}
                className="flex-1 py-2.5 px-4 rounded-xl bg-accent text-white text-xs font-medium hover:bg-accent/90 transition-colors cursor-pointer shadow-lg shadow-accent/20"
              >
                Очистить
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Reset Settings */}
      {isResetModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
          <div className="bg-surface border border-white/10 rounded-2xl p-5 max-w-sm w-full shadow-2xl space-y-4">
            <div className="w-12 h-12 rounded-xl bg-rose-500/10 flex items-center justify-center text-rose-400 mx-auto">
              <RotateCcw size={24} />
            </div>

            <div className="text-center space-y-1">
              <h3 className="text-base font-semibold text-text-primary">
                Сбросить настройки?
              </h3>
              <p className="text-xs text-text-secondary leading-relaxed">
                Все параметры читалки вернутся к значениям по умолчанию.
              </p>
            </div>

            <div className="flex gap-2.5 pt-1">
              <button
                type="button"
                onClick={() => setIsResetModalOpen(false)}
                className="flex-1 py-2.5 px-4 rounded-xl border border-white/10 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-white/5 transition-colors cursor-pointer"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleResetSettings}
                className="flex-1 py-2.5 px-4 rounded-xl bg-rose-500 text-white text-xs font-medium hover:bg-rose-600 transition-colors cursor-pointer"
              >
                Сбросить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
