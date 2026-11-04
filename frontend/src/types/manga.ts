/**
 * TypeScript interfaces matching backend Pydantic schemas:
 * MangaListRead, GenreRead, and AuthorRead.
 */

export interface GenreRead {
  id: number
  name: string
  slug: string
}

export interface AuthorRead {
  id: number
  name: string
  role?: string | null
}

export interface MangaItem {
  id: number
  title: string
  slug: string
  original_title?: string | null
  cover_url?: string | null
  status: string
  type: string
  release_year?: number | null
  rating: number
  views_count: number
  genres: GenreRead[]
  authors: AuthorRead[]
}
