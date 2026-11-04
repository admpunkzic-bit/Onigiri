import { Wifi, WifiOff, Loader2 } from 'lucide-react'
import type { ServerState } from '../hooks/useServerHealth'

interface ServerStatusProps {
  state: ServerState
  onRetry?: () => void
}

const config: Record<ServerState, { label: string; dotClass: string }> = {
  connected: {
    label: 'Подключено',
    dotClass: 'bg-emerald-400',
  },
  connecting: {
    label: 'Подключение…',
    dotClass: 'bg-amber-400',
  },
  unavailable: {
    label: 'Сервер недоступен',
    dotClass: 'bg-red-400',
  },
}

export default function ServerStatus({ state, onRetry }: ServerStatusProps) {
  const { label, dotClass } = config[state]

  const Icon =
    state === 'connecting' ? Loader2 : state === 'connected' ? Wifi : WifiOff

  return (
    <button
      onClick={onRetry}
      disabled={state === 'connecting'}
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface border border-white/5 transition-colors hover:border-white/10 disabled:opacity-70"
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
      <Icon
        size={14}
        className={`text-text-secondary ${state === 'connecting' ? 'animate-spin' : ''}`}
      />
      <span className="text-[11px] text-text-secondary">{label}</span>
    </button>
  )
}
