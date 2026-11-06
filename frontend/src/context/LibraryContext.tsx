import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react'
import type { MangaItem } from '../types/manga'
import {
  fetchLibrary,
  fetchLibraryIds,
  addToLibrary,
  removeFromLibrary,
} from '../services/api'

interface LibraryContextValue {
  starredIds: Set<number>
  libraryItems: MangaItem[]
  isLoading: boolean
  isStarred: (mangaId: number) => boolean
  toggleStar: (manga: MangaItem) => Promise<void>
  refreshLibrary: () => Promise<void>
}

const LibraryContext = createContext<LibraryContextValue | undefined>(undefined)

export function LibraryProvider({ children }: { children: ReactNode }) {
  const [starredIds, setStarredIds] = useState<Set<number>>(new Set())
  const [libraryItems, setLibraryItems] = useState<MangaItem[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)

  const refreshLibrary = useCallback(async () => {
    try {
      const [ids, items] = await Promise.all([fetchLibraryIds(), fetchLibrary()])
      setStarredIds(new Set(ids))
      setLibraryItems(items)
    } catch (err) {
      console.error('Failed to load library:', err)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshLibrary()
  }, [refreshLibrary])

  const isStarred = useCallback(
    (mangaId: number) => starredIds.has(mangaId),
    [starredIds]
  )

  const toggleStar = useCallback(
    async (manga: MangaItem) => {
      const currentlyStarred = starredIds.has(manga.id)

      // Optimistic update
      setStarredIds((prev) => {
        const next = new Set(prev)
        if (currentlyStarred) {
          next.delete(manga.id)
        } else {
          next.add(manga.id)
        }
        return next
      })

      setLibraryItems((prev) => {
        if (currentlyStarred) {
          return prev.filter((item) => item.id !== manga.id)
        } else {
          return [manga, ...prev.filter((item) => item.id !== manga.id)]
        }
      })

      try {
        if (currentlyStarred) {
          await removeFromLibrary(manga.id)
        } else {
          await addToLibrary(manga)
        }
      } catch (err) {
        console.error('Failed to toggle library star:', err)
        // Rollback state on failure
        setStarredIds((prev) => {
          const next = new Set(prev)
          if (currentlyStarred) {
            next.add(manga.id)
          } else {
            next.delete(manga.id)
          }
          return next
        })
        setLibraryItems((prev) => {
          if (currentlyStarred) {
            return [manga, ...prev]
          } else {
            return prev.filter((item) => item.id !== manga.id)
          }
        })
      }
    },
    [starredIds]
  )

  return (
    <LibraryContext.Provider
      value={{
        starredIds,
        libraryItems,
        isLoading,
        isStarred,
        toggleStar,
        refreshLibrary,
      }}
    >
      {children}
    </LibraryContext.Provider>
  )
}

export function useLibrary(): LibraryContextValue {
  const context = useContext(LibraryContext)
  if (!context) {
    throw new Error('useLibrary must be used within a LibraryProvider')
  }
  return context
}
