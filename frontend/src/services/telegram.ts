import type {
  TelegramWebApp,
  TelegramSafeAreaInset,
  TelegramContentSafeAreaInset,
  TelegramThemeParams,
} from '../types/telegram'

/**
 * Compares two semantic version strings (e.g. "7.10" vs "7.9").
 * Returns:
 *   1 if v1 > v2
 *  -1 if v1 < v2
 *   0 if v1 === v2
 */
export function compareVersions(v1: string, v2: string): number {
  const parts1 = v1.split('.').map((p) => {
    const num = parseInt(p, 10)
    return Number.isNaN(num) ? 0 : num
  })
  const parts2 = v2.split('.').map((p) => {
    const num = parseInt(p, 10)
    return Number.isNaN(num) ? 0 : num
  })

  const maxLength = Math.max(parts1.length, parts2.length)
  for (let i = 0; i < maxLength; i++) {
    const num1 = parts1[i] ?? 0
    const num2 = parts2[i] ?? 0
    if (num1 > num2) return 1
    if (num1 < num2) return -1
  }

  return 0
}

/**
 * Safely retrieves the Telegram WebApp object if present.
 */
export function getTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === 'undefined') return null
  return window.Telegram?.WebApp ?? null
}

/**
 * Checks whether the application is running inside Telegram WebApp environment.
 *
 * Criterion:
 * Official telegram-web-app.js always initializes in window even in regular browsers,
 * but sets `platform: 'unknown'` and `initData: ''`.
 * Inside real Telegram clients (iOS, Android, Desktop, Web, macOS), `platform`
 * is set to a recognized client name (e.g. 'ios', 'android', 'tdesktop', 'web')
 * and/or `initData` is populated from launch query/hash params.
 */
export function isTelegramEnvironment(): boolean {
  const tg = getTelegramWebApp()
  if (!tg) return false

  const hasKnownPlatform =
    typeof tg.platform === 'string' &&
    tg.platform !== 'unknown' &&
    tg.platform.trim().length > 0

  const hasInitData =
    typeof tg.initData === 'string' && tg.initData.trim().length > 0

  return hasKnownPlatform || hasInitData
}

/**
 * Checks whether Telegram WebApp supports at least the specified API version.
 * First delegates to native `isVersionAtLeast` method if available;
 * otherwise uses component-based version comparison.
 */
export function isVersionAtLeast(version: string): boolean {
  const tg = getTelegramWebApp()
  if (!tg) return false

  if (typeof tg.isVersionAtLeast === 'function') {
    try {
      return tg.isVersionAtLeast(version)
    } catch {
      // Fallback to component comparison on unexpected error
    }
  }

  if (typeof tg.version === 'string' && tg.version.trim().length > 0) {
    return compareVersions(tg.version, version) >= 0
  }

  return false
}

/**
 * Safely calls WebApp.ready() if available.
 */
export function safeReady(): void {
  const tg = getTelegramWebApp()
  if (tg && typeof tg.ready === 'function') {
    try {
      tg.ready()
    } catch {
      // Ignore errors in non-standard environments
    }
  }
}

/**
 * Safely calls WebApp.expand() if available.
 */
export function safeExpand(): void {
  const tg = getTelegramWebApp()
  if (tg && typeof tg.expand === 'function') {
    try {
      tg.expand()
    } catch {
      // Ignore errors in non-standard environments
    }
  }
}

/**
 * Safely gets safeAreaInset with strict Bot API 8.0+ version verification.
 * Guaranteed to return 0 on API versions below 8.0 or outside Telegram.
 */
export function getSafeAreaInset(): TelegramSafeAreaInset {
  const tg = getTelegramWebApp()
  if (!tg || !isVersionAtLeast('8.0')) {
    return { top: 0, bottom: 0, left: 0, right: 0 }
  }

  return {
    top: typeof tg.safeAreaInset?.top === 'number' ? tg.safeAreaInset.top : 0,
    bottom: typeof tg.safeAreaInset?.bottom === 'number' ? tg.safeAreaInset.bottom : 0,
    left: typeof tg.safeAreaInset?.left === 'number' ? tg.safeAreaInset.left : 0,
    right: typeof tg.safeAreaInset?.right === 'number' ? tg.safeAreaInset.right : 0,
  }
}

/**
 * Safely gets contentSafeAreaInset with strict Bot API 8.0+ version verification.
 * Guaranteed to return 0 on API versions below 8.0 or outside Telegram.
 */
export function getContentSafeAreaInset(): TelegramContentSafeAreaInset {
  const tg = getTelegramWebApp()
  if (!tg || !isVersionAtLeast('8.0')) {
    return { top: 0, bottom: 0, left: 0, right: 0 }
  }

  return {
    top: typeof tg.contentSafeAreaInset?.top === 'number' ? tg.contentSafeAreaInset.top : 0,
    bottom: typeof tg.contentSafeAreaInset?.bottom === 'number' ? tg.contentSafeAreaInset.bottom : 0,
    left: typeof tg.contentSafeAreaInset?.left === 'number' ? tg.contentSafeAreaInset.left : 0,
    right: typeof tg.contentSafeAreaInset?.right === 'number' ? tg.contentSafeAreaInset.right : 0,
  }
}

/**
 * Safely gets current theme params with fallback.
 */
export function getThemeParams(): TelegramThemeParams {
  const tg = getTelegramWebApp()
  return tg?.themeParams ?? {}
}

/**
 * Safely gets current color scheme ('dark' | 'light').
 */
export function getColorScheme(): 'dark' | 'light' {
  const tg = getTelegramWebApp()
  return tg?.colorScheme === 'light' ? 'light' : 'dark'
}
