import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

export interface AppSettings {
  defaultReadingMode: 'vertical' | 'paged'
  rememberLastMode: boolean
  lastReadingMode: 'vertical' | 'paged'
  autoNextChapter: boolean
  preloadPages: boolean
  autoHideControls: boolean
}

export const DEFAULT_SETTINGS: AppSettings = {
  defaultReadingMode: 'vertical',
  rememberLastMode: true,
  lastReadingMode: 'vertical',
  autoNextChapter: true,
  preloadPages: true,
  autoHideControls: true,
}

const SETTINGS_STORAGE_KEY = 'onigiri_app_settings'
const LEGACY_READER_MODE_KEY = 'onigiri_reader_mode'

interface SettingsContextValue {
  settings: AppSettings
  updateSettings: (partial: Partial<AppSettings>) => void
  resetSettings: () => void
  getEffectiveReadingMode: () => 'vertical' | 'paged'
  setLastReadingMode: (mode: 'vertical' | 'paged') => void
}

const SettingsContext = createContext<SettingsContextValue | undefined>(undefined)

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(() => {
    if (typeof window === 'undefined') return DEFAULT_SETTINGS
    try {
      const raw = localStorage.getItem(SETTINGS_STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)
        return { ...DEFAULT_SETTINGS, ...parsed }
      }
      // Migrate legacy key if present
      const legacyMode = localStorage.getItem(LEGACY_READER_MODE_KEY)
      if (legacyMode === 'paged' || legacyMode === 'vertical') {
        return {
          ...DEFAULT_SETTINGS,
          defaultReadingMode: legacyMode,
          lastReadingMode: legacyMode,
        }
      }
    } catch {
      // Ignore parse errors, fallback to default
    }
    return DEFAULT_SETTINGS
  })

  // Synchronize settings to localStorage on change
  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings))
      // Keep legacy key synced for backwards compatibility
      localStorage.setItem(LEGACY_READER_MODE_KEY, settings.lastReadingMode)
    } catch {
      // Ignore storage quota errors
    }
  }, [settings])

  const updateSettings = useCallback((partial: Partial<AppSettings>) => {
    setSettings((prev) => ({ ...prev, ...partial }))
  }, [])

  const resetSettings = useCallback(() => {
    setSettings(DEFAULT_SETTINGS)
  }, [])

  const getEffectiveReadingMode = useCallback((): 'vertical' | 'paged' => {
    if (settings.rememberLastMode) {
      return settings.lastReadingMode || settings.defaultReadingMode
    }
    return settings.defaultReadingMode
  }, [settings])

  const setLastReadingMode = useCallback((mode: 'vertical' | 'paged') => {
    setSettings((prev) => {
      if (prev.lastReadingMode === mode) return prev
      return { ...prev, lastReadingMode: mode }
    })
  }, [])

  return (
    <SettingsContext.Provider
      value={{
        settings,
        updateSettings,
        resetSettings,
        getEffectiveReadingMode,
        setLastReadingMode,
      }}
    >
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings(): SettingsContextValue {
  const context = useContext(SettingsContext)
  if (!context) {
    throw new Error('useSettings must be used within a SettingsProvider')
  }
  return context
}
