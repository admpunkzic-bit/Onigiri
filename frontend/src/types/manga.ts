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

export interface TranslationVariant {
  id: string
  source_name: string
  scanlation_group?: string | null
  translator_name: string
  display_name: string
  chapters_count: number
  volumes_count: number
  min_chapter?: number | null
  max_chapter?: number | null
  has_gaps: boolean
  gaps_count: number
  available_pages_count: number
  is_working: boolean
  is_default: boolean
}

export interface ChapterItem {
  id: number
  manga_id: number
  source_chapter_id?: string | null
  chapter_number?: number | null
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
  translations?: TranslationVariant[]
  selected_translation_id?: string | null
}

export interface ChapterReaderPageItem {
  page_number: number
  image_url: string
}

export interface ChapterReaderDetail {
  chapter_id: number
  manga_id: number
  manga_title: string
  cover_url?: string | null
  manga_slug?: string | null
  chapter_number?: number | null
  volume_number?: number | null
  title?: string | null
  scanlation_group?: string | null
  translation_id?: string | null
  total_pages: number
  pages: ChapterReaderPageItem[]
  prev_chapter_id?: number | null
  next_chapter_id?: number | null
}

export interface ReadingProgress {
  manga_id: number
  chapter_id: number
  translation_id?: string | null
  chapter_number?: number | null
  chapter_title?: string | null
  page_number: number
  total_pages?: number | null
  updated_at: string
}

export interface ReadingHistoryItem {
  manga_id: number
  manga_slug: string
  manga_title: string
  cover_url?: string | null
  manga_status?: string | null
  chapter_id: number
  translation_id?: string | null
  scanlation_group?: string | null
  chapter_number?: number | null
  volume_number?: number | null
  chapter_title?: string | null
  page_number: number
  total_pages?: number | null
  updated_at: string
}
