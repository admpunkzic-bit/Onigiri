/**
 * API service for communicating with the Onigiri backend.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export async function fetchHealth(): Promise<{ status: string; service: string; version: string; timestamp: string }> {
  const response = await fetch(`${API_BASE_URL}/health`)
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }
  return response.json()
}
