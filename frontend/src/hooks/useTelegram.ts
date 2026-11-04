import { useEffect, useState, useCallback } from 'react'
import type {
  TelegramThemeParams,
  TelegramSafeAreaInset,
  TelegramContentSafeAreaInset,
  TelegramViewportChangedPayload,
} from '../types/telegram'
import {
  getTelegramWebApp,
  isTelegramEnvironment,
  safeReady,
  safeExpand,
  getSafeAreaInset,
  getContentSafeAreaInset,
  getThemeParams,
  getColorScheme,
} from '../services/telegram'

export interface TelegramState {
  isTelegram: boolean
  colorScheme: 'dark' | 'light'
  themeParams: TelegramThemeParams
  viewportHeight: number
  viewportStableHeight: number
  isStateStable: boolean
  safeAreaInset: TelegramSafeAreaInset
  contentSafeAreaInset: TelegramContentSafeAreaInset
}

const defaultSafeArea: TelegramSafeAreaInset = {
  top: 0,
  bottom: 0,
  left: 0,
  right: 0,
}

const defaultContentSafeArea: TelegramContentSafeAreaInset = {
  top: 0,
  bottom: 0,
  left: 0,
  right: 0,
}

const TG_CSS_VARIABLES = [
  '--tg-viewport-height',
  '--tg-viewport-stable-height',
  '--tg-safe-area-top',
  '--tg-safe-area-bottom',
  '--tg-safe-area-left',
  '--tg-safe-area-right',
  '--tg-content-safe-area-top',
  '--tg-content-safe-area-bottom',
  '--tg-content-safe-area-left',
  '--tg-content-safe-area-right',
] as const

/**
 * Hook for integrating with Telegram WebApp API.
 * Safely falls back to defaults when run in standard browser.
 */
export function useTelegram(): TelegramState {
  const [state, setState] = useState<TelegramState>(() => {
    const isTg = isTelegramEnvironment()
    const tg = getTelegramWebApp()

    if (!isTg || !tg) {
      return {
        isTelegram: false,
        colorScheme: 'dark',
        themeParams: {},
        viewportHeight: typeof window !== 'undefined' ? window.innerHeight : 0,
        viewportStableHeight: typeof window !== 'undefined' ? window.innerHeight : 0,
        isStateStable: true,
        safeAreaInset: defaultSafeArea,
        contentSafeAreaInset: defaultContentSafeArea,
      }
    }

    return {
      isTelegram: true,
      colorScheme: getColorScheme(),
      themeParams: getThemeParams(),
      viewportHeight: tg.viewportHeight || (typeof window !== 'undefined' ? window.innerHeight : 0),
      viewportStableHeight: tg.viewportStableHeight || (typeof window !== 'undefined' ? window.innerHeight : 0),
      isStateStable: true,
      safeAreaInset: getSafeAreaInset(),
      contentSafeAreaInset: getContentSafeAreaInset(),
    }
  })

  // Synchronize CSS custom properties on :root
  const updateCssVariables = useCallback(
    (
      vh: number,
      vsh: number,
      safeArea: TelegramSafeAreaInset,
      contentSafeArea: TelegramContentSafeAreaInset,
    ) => {
      if (typeof document === 'undefined') return
      const root = document.documentElement

      root.style.setProperty('--tg-viewport-height', `${vh}px`)
      root.style.setProperty('--tg-viewport-stable-height', `${vsh}px`)

      root.style.setProperty('--tg-safe-area-top', `${safeArea.top}px`)
      root.style.setProperty('--tg-safe-area-bottom', `${safeArea.bottom}px`)
      root.style.setProperty('--tg-safe-area-left', `${safeArea.left}px`)
      root.style.setProperty('--tg-safe-area-right', `${safeArea.right}px`)

      root.style.setProperty('--tg-content-safe-area-top', `${contentSafeArea.top}px`)
      root.style.setProperty('--tg-content-safe-area-bottom', `${contentSafeArea.bottom}px`)
      root.style.setProperty('--tg-content-safe-area-left', `${contentSafeArea.left}px`)
      root.style.setProperty('--tg-content-safe-area-right', `${contentSafeArea.right}px`)
    },
    [],
  )

  useEffect(() => {
    const isTg = isTelegramEnvironment()
    const tg = getTelegramWebApp()

    if (!isTg || !tg) {
      // In regular browser, sync CSS variables with window height
      const handleResize = () => {
        const vh = window.innerHeight
        updateCssVariables(vh, vh, defaultSafeArea, defaultContentSafeArea)
      }
      handleResize()
      window.addEventListener('resize', handleResize)

      return () => {
        window.removeEventListener('resize', handleResize)
        if (typeof document !== 'undefined') {
          const root = document.documentElement
          for (const variable of TG_CSS_VARIABLES) {
            root.style.removeProperty(variable)
          }
        }
      }
    }

    // 1. Mark ready and expand inside Telegram
    safeReady()
    safeExpand()

    // 2. Set dark background & header to match Onigiri theme
    if (typeof tg.setHeaderColor === 'function') {
      try {
        tg.setHeaderColor('#101116')
      } catch {
        // unsupported in some older clients
      }
    }
    if (typeof tg.setBackgroundColor === 'function') {
      try {
        tg.setBackgroundColor('#101116')
      } catch {
        // unsupported in some older clients
      }
    }

    // Initial CSS variables sync
    const initialVh = tg.viewportHeight || window.innerHeight
    const initialVsh = tg.viewportStableHeight || window.innerHeight
    const initialSafeArea = getSafeAreaInset()
    const initialContentSafeArea = getContentSafeAreaInset()

    updateCssVariables(initialVh, initialVsh, initialSafeArea, initialContentSafeArea)

    // 3. Event handlers
    const handleThemeChange = () => {
      const newColorScheme = getColorScheme()
      const newThemeParams = getThemeParams()
      setState((prev) => ({
        ...prev,
        colorScheme: newColorScheme,
        themeParams: newThemeParams,
      }))
    }

    const handleViewportChange = (eventData?: TelegramViewportChangedPayload) => {
      const newVh = tg.viewportHeight || window.innerHeight
      const newVsh = tg.viewportStableHeight || window.innerHeight
      const isStable = eventData?.isStateStable ?? true

      setState((prev) => {
        updateCssVariables(newVh, newVsh, prev.safeAreaInset, prev.contentSafeAreaInset)
        return {
          ...prev,
          viewportHeight: newVh,
          viewportStableHeight: newVsh,
          isStateStable: isStable,
        }
      })
    }

    const handleSafeAreaChange = () => {
      const newSafeArea = getSafeAreaInset()
      setState((prev) => {
        updateCssVariables(prev.viewportHeight, prev.viewportStableHeight, newSafeArea, prev.contentSafeAreaInset)
        return {
          ...prev,
          safeAreaInset: newSafeArea,
        }
      })
    }

    const handleContentSafeAreaChange = () => {
      const newContentSafeArea = getContentSafeAreaInset()
      setState((prev) => {
        updateCssVariables(prev.viewportHeight, prev.viewportStableHeight, prev.safeAreaInset, newContentSafeArea)
        return {
          ...prev,
          contentSafeAreaInset: newContentSafeArea,
        }
      })
    }

    // 4. Independent event subscriptions
    // Requires BOTH onEvent and offEvent to be available to guarantee clean teardown
    const hasEventApi =
      typeof tg.onEvent === 'function' && typeof tg.offEvent === 'function'

    const registeredEvents: Array<{
      name: string
      handler: (...args: any[]) => void
    }> = []

    if (hasEventApi) {
      const subscribe = (eventName: string, handler: (...args: any[]) => void) => {
        try {
          tg.onEvent!(eventName, handler)
          registeredEvents.push({ name: eventName, handler })
        } catch {
          // Failure on one event does not block others
        }
      }

      subscribe('themeChanged', handleThemeChange)
      subscribe('viewportChanged', handleViewportChange)
      subscribe('safeAreaChanged', handleSafeAreaChange)
      subscribe('contentSafeAreaChanged', handleContentSafeAreaChange)
    }

    // 5. Cleanup only successfully registered handlers and reset our CSS variables
    return () => {
      if (hasEventApi) {
        for (const { name, handler } of registeredEvents) {
          try {
            tg.offEvent!(name, handler)
          } catch {
            // ignore individual handler removal failure
          }
        }
      }

      if (typeof document !== 'undefined') {
        const root = document.documentElement
        for (const variable of TG_CSS_VARIABLES) {
          root.style.removeProperty(variable)
        }
      }
    }
  }, [updateCssVariables])

  return state
}
