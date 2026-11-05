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

export interface ChapterItem {
  id: number
  manga_id: number
  source_chapter_id?: string | null
  chapter_number: number
  volume_number?: number | null
  title?: string | null
  language?: string
  scanlation_group?: string | null
  published_at?: string | null
}

export interface MangaDetail extends MangaItem {
  description?: string | null
  banner_url?: string | null
  chapters: ChapterItem[]
}
