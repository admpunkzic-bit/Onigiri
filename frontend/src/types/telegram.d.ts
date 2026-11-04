/**
 * Telegram WebApp API type definitions.
 * Follows Bot API 6.0 - 8.0 specifications.
 */

export interface TelegramThemeParams {
  bg_color?: string
  text_color?: string
  hint_color?: string
  link_color?: string
  button_color?: string
  button_text_color?: string
  secondary_bg_color?: string
  header_bg_color?: string
  bottom_bar_bg_color?: string
  accent_text_color?: string
  section_bg_color?: string
  section_header_text_color?: string
  subtitle_text_color?: string
  destructive_text_color?: string
  [key: string]: string | undefined
}

export interface TelegramSafeAreaInset {
  top: number
  bottom: number
  left: number
  right: number
}

export interface TelegramContentSafeAreaInset {
  top: number
  bottom: number
  left: number
  right: number
}

export interface TelegramViewportChangedPayload {
  isStateStable: boolean
}

export interface TelegramWebApp {
  initData: string
  initDataUnsafe: Record<string, unknown>
  version: string
  platform: string
  colorScheme: 'light' | 'dark'
  themeParams: TelegramThemeParams
  isExpanded: boolean
  viewportHeight: number
  viewportStableHeight: number
  headerColor?: string
  backgroundColor?: string
  safeAreaInset?: TelegramSafeAreaInset
  contentSafeAreaInset?: TelegramContentSafeAreaInset

  isVersionAtLeast?: (version: string) => boolean
  setHeaderColor?: (color: string) => void
  setBackgroundColor?: (color: string) => void
  ready?: () => void
  expand?: () => void
  close?: () => void

  onEvent?: (
    eventType: 'themeChanged' | 'viewportChanged' | 'safeAreaChanged' | 'contentSafeAreaChanged' | string,
    eventHandler: (...args: any[]) => void,
  ) => void
  offEvent?: (
    eventType: 'themeChanged' | 'viewportChanged' | 'safeAreaChanged' | 'contentSafeAreaChanged' | string,
    eventHandler: (...args: any[]) => void,
  ) => void
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }
}
