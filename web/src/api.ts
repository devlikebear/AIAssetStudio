// Typed client for the backend HTTP API (src/aiassetstudio/api/app.py).

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
export type AssetStatus = 'candidate' | 'selected' | 'rejected'
export type AssetKind = 'sprite' | 'icon' | 'bgm' | 'animation' | 'page_image' | 'narration' | 'book_export'
export type PageStatus = 'draft' | 'queued' | 'candidate' | 'approved' | 'redo'

export interface Project {
  id: number
  slug: string
  name: string
  style: string
  export_dir: string | null
  pixel_art: boolean
  logical_width: number | null
  logical_height: number | null
  icon_size: number | null
  max_colors: number | null
  palette: string[] | null
  reference_image: string | null
  animation_cloud?: boolean // animations may send this project's sprites to OpenAI (codex); absent before schema v2
  created_at: string
  updated_at: string
}

export interface Job {
  id: string
  project_id: number
  project: string
  kind: 'image' | 'bgm' | 'animation' | 'page_image' | 'narration' | 'book_export'
  family: string
  params: {
    kind?: string
    description?: string
    count?: number
    seed?: number | null
    // BGM jobs
    brief?: string
    bpm?: number
    seconds?: number
    loop?: boolean
    vocal?: boolean
    lyrics?: string | null
    keyscale?: string
    // animation jobs
    asset_id?: string
  }
  status: JobStatus
  stage: string | null
  error: string | null
  timings: Record<string, unknown> | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface AlphaStats {
  transparent: number
  opaque: number
  partial: number
  border_mean: number
  border_max: number
}

/** How pixel art was fitted to its canvas: the model's own block grid at a whole factor, or stretched. */
export interface PixelFit {
  fit: 'native' | 'stretch'
  cell_px?: [number, number] // the model's block width and height in the generated image, when a grid was found
  native_size?: [number, number] // the subject in blocks
  scale?: number // native: the whole factor
  reason?: string // stretch: "no grid", "uneven grid", "larger than the canvas", "empty"
}

/** Set on assets cleaned up into pixel art; `processed` is then width x height (the logical size). */
export interface PixelMeta {
  width: number
  height: number
  max_colors: number
  colors_used: number
  palette: string[] | null
  fit?: PixelFit // absent on assets made before 2026-09-25
}

/** Where the loop of a BGM candidate lies in the trimmed song, and how its seam compares to ordinary steps. */
export interface LoopMeta {
  bpm?: number // the tempo the loop was cut at: detected in the song, else the requested one
  start_s: number
  end_s: number
  bars: number
  seam_ratio: number
}

/** A game animation tag: frames `from`..`to` (0-based, inclusive), `duration` seconds each. */
export interface AnimationTag {
  name: string
  from: number
  to: number
  duration: number
}

/** How an animation's frames were fitted to the base sprite: sizes are opaque-pixel widths x heights (medians). */
export interface AnimationFit {
  base_size: [number, number]
  frame_sizes?: [number, number][]
  idle_size?: [number, number]
  walk_size?: [number, number]
  idle_height: number
  size_ok: boolean // idle frames within 2 cells of the base's width and 1 of its height
  ground_row: number // the row the feet stand on, 0 = top
  colors_used: number
  warnings?: string[]
}

export interface AnimationMeta {
  frames: number
  cell: [number, number]
  tags: AnimationTag[]
  max_colors?: number
  files?: string[]
}

export interface AssetMeta {
  pixel?: PixelMeta
  // animations
  base_asset?: string
  animation?: AnimationMeta
  fit?: AnimationFit
  cloud?: { provider: string; sent?: string[] }
  spritegen?: {
    version?: string | null
    warnings?: string[]
    inspect?: { ok?: boolean | null; errors?: string[] | null; warnings?: string[] | null }
  }
  reference?: { mode: string; file: string }
  // BGM
  bpm?: number
  keyscale?: string
  tags?: string
  style?: string
  lyrics?: string
  vocal?: boolean
  requested_s?: number
  raw_s?: number
  trimmed_s?: number
  length_s?: number
  loop?: LoopMeta
  loop_error?: string
  ogg_error?: string
  description?: string
  prompt?: string
  seed?: number
  workflow?: string
  models?: Record<string, string>
  steps?: number
  sampler?: string
  size_raw?: [number, number]
  size_processed?: [number, number]
  alpha_raw?: AlphaStats
  alpha_processed?: AlphaStats
  timings?: Record<string, number>
  exports?: { path: string; at: string }[]
  [key: string]: unknown
}

export interface Asset {
  id: string
  job_id: string
  project_id: number
  project: string
  kind: AssetKind
  status: AssetStatus
  seed: number | null
  files: Record<string, string> // role -> URL
  meta: AssetMeta
  created_at: string
}

export interface JobWithAssets extends Job {
  assets: Asset[]
}

export interface SourceRef {
  node_id: string
  content_version: number
  label?: string
}

export interface Page {
  id: string
  book_id: string
  number: number
  text: string
  image_prompt: string
  people: string[]
  props: string[]
  place: string | null
  source_refs: SourceRef[]
  image_asset_id: string | null
  status: PageStatus
  note: string | null
  candidates: Asset[]
  narration_asset_id: string | null
  narration_status: PageStatus
  narration_note: string | null
  narration_candidates: Asset[]
}

export interface Sheet {
  id: string
  kind: 'character' | 'place' | 'prop'
  name: string
  description: string
  asset_id: string | null
  asset: Asset | null
}

export interface BookSummary {
  id: string
  project: string
  title: string
  created_at: string
}

export interface Book extends BookSummary {
  width: number
  height: number
  cover_page: number | null
  pages: Page[]
  sheets: Sheet[]
  counts: Partial<Record<PageStatus, number>>
  narration_counts: Partial<Record<PageStatus, number>>
  license_class: 'open' | 'community' | 'unknown' | 'research_only' | null
}

export interface FamilyStatus {
  ok: boolean
  missing_nodes: string[]
  missing_models: string[]
  reason: string | null
}

export interface PackLicense {
  id: string
  name: string
  class_: string
  url: string
  summary_ko: string
  accepted: boolean
}

export interface Pack {
  id: string
  title: string
  feature: string
  version: string
  download_size: number
  tested: { vram_gb: number; ram_gb: number; disk_gb: number; os: string }
  gated: boolean
  licenses: PackLicense[]
  status: 'not_installed' | 'installing' | 'installed' | 'failed' | 'cancelled'
  stage: string | null
  error: string | null
  license_changed: boolean
  installed_version: string | null
  log_tail: string
}

export interface Status {
  backend: 'ok'
  comfy: { up: boolean; url: string; vram_free_mb?: number; ram_free_mb?: number; error?: string }
  preflight: Record<string, FamilyStatus>
  animation?: { ok: boolean; reason?: string | null; login?: string }
  queue: {
    running: string | null
    queued: number
    current: { id: string; project: string; kind: string; stage: string | null; elapsed_s: number } | null
  }
  packs?: Record<string, Pack['status']>
  gallery_url: string
  repo_dir?: string // this checkout, for the MCP registration command (a backend older than the gallery lacks it)
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    })
  } catch {
    throw new ApiError(0, '백엔드에 연결할 수 없습니다')
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

function query(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter((entry): entry is [string, string] => Boolean(entry[1]))
  return entries.length ? `?${new URLSearchParams(entries)}` : ''
}

export const getStatus = () => request<Status>('/api/status')
export const listProjects = () => request<Project[]>('/api/projects')
export const getProject = (slug: string) => request<Project>(`/api/projects/${encodeURIComponent(slug)}`)
// The copy's path is content-hashed, so it doubles as a cache key when the reference changes.
export const projectReferenceUrl = (project: Project) =>
  `/api/projects/${encodeURIComponent(project.slug)}/reference?v=${encodeURIComponent(project.reference_image ?? '')}`
export const listJobs = (filters: { project?: string; status?: string } = {}) =>
  request<Job[]>(`/api/jobs${query(filters)}`)
export const getJob = (id: string) => request<JobWithAssets>(`/api/jobs/${encodeURIComponent(id)}`)
export const listAssets = (filters: { project?: string; kind?: string; status?: string; job_id?: string } = {}) =>
  request<Asset[]>(`/api/assets${query(filters)}`)
export const setAssetStatus = (id: string, status: AssetStatus) =>
  request<Asset>(`/api/assets/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ status }) })
export const exportAsset = (id: string, options: { dest_dir?: string; name?: string } = {}) =>
  request<{ paths: string[] }>(`/api/assets/${encodeURIComponent(id)}/export`, {
    method: 'POST',
    body: JSON.stringify(options),
  })
export const cancelJob = (id: string) =>
  request<JobWithAssets>(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
export const listBooks = (project: string) => request<BookSummary[]>(`/api/books${query({ project })}`)
export const getBook = (id: string) => request<Book>(`/api/books/${encodeURIComponent(id)}`)
export const updatePage = (
  id: string,
  fields: {
    status?: 'approved' | 'redo' | 'draft'
    note?: string | null
    image_asset_id?: string
    narration_status?: 'approved' | 'redo' | 'draft'
    narration_note?: string | null
    narration_asset_id?: string
  },
) => request<Page>(`/api/pages/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(fields) })
export const exportBook = (id: string, allowDraft: boolean, format: 'pdf' | 'mp3' = 'pdf') =>
  request<{ job_id: string }>(`/api/books/${encodeURIComponent(id)}/export`, {
    method: 'POST',
    body: JSON.stringify({ allow_draft: allowDraft, format }),
  })
export const narrateBook = (id: string) =>
  request<{ job_ids: string[] }>(`/api/books/${encodeURIComponent(id)}/narrate`, {
    method: 'POST',
    body: JSON.stringify({}),
  })

// Only the gallery may agree to a license; the backend tells who asks by this header.
const GALLERY = { 'X-Studio-Client': 'gallery' }
const packPath = (id: string, action = '') => `/api/packs/${encodeURIComponent(id)}${action}`

export const listPacks = () => request<Pack[]>('/api/packs')
export const getPack = (id: string) => request<Pack>(packPath(id))
export const acceptPack = (id: string, licenses: string[]) =>
  request<Pack>(packPath(id, '/accept'), { method: 'POST', headers: GALLERY, body: JSON.stringify({ licenses }) })
export const installPack = (id: string) => request<Pack>(packPath(id, '/install'), { method: 'POST', headers: GALLERY })
export const cancelPack = (id: string) => request<Pack>(packPath(id, '/cancel'), { method: 'POST', headers: GALLERY })
export const removePack = (id: string) => request<Pack>(packPath(id), { method: 'DELETE', headers: GALLERY })
