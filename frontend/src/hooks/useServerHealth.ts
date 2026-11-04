import { useEffect, useState, useCallback } from 'react'
import { fetchHealth, type HealthResponse, NetworkError } from '../services/api'

export type ServerState = 'connecting' | 'connected' | 'unavailable'

interface UseServerHealthReturn {
  state: ServerState
  data: HealthResponse | null
  refresh: () => void
}

/**
 * Hook that checks the backend health status.
 *
 * - Runs once on mount.
 * - Can be manually refreshed via `refresh()`.
 * - Automatically retries every 30s when the server is unavailable,
 *   and stops polling once connected.
 */
export function useServerHealth(): UseServerHealthReturn {
  const [state, setState] = useState<ServerState>('connecting')
  const [data, setData] = useState<HealthResponse | null>(null)

  const check = useCallback(async () => {
    setState('connecting')
    try {
      const result = await fetchHealth()
      setData(result)
      setState('connected')
    } catch (error) {
      setData(null)
      if (error instanceof NetworkError) {
        setState('unavailable')
      } else {
        setState('unavailable')
      }
    }
  }, [])

  // Initial check on mount + retry interval when unavailable
  useEffect(() => {
    check()
  }, [check])

  useEffect(() => {
    if (state !== 'unavailable') return

    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [state, check])

  return { state, data, refresh: check }
}
