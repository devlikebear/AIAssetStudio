import type { AnimationTag, Asset, Job, PageStatus, PixelFit } from './api'

const relative = new Intl.RelativeTimeFormat('ko', { numeric: 'auto' })

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return ''
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 45) return '방금'
  if (abs < 3600) return relative.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), 'hour')
  if (abs < 86400 * 7) return relative.format(Math.round(seconds / 86400), 'day')
  return new Date(iso).toLocaleDateString('ko-KR')
}

export function duration(seconds: number | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${Math.round(seconds)}초`
  return `${Math.floor(seconds / 60)}분 ${Math.round(seconds % 60)}초`
}

/** The file a song plays by default: the loop if there is one, OGG (small) before WAV. */
export function playableFile(asset: Asset): string | undefined {
  const f = asset.files
  return f.loop_ogg ?? f.loop_wav ?? f.full_ogg ?? f.full_wav
}

export function songSummary(asset: Asset): string {
  const m = asset.meta
  const bpm = m.loop?.bpm ?? m.bpm
  return [
    `${bpm == null ? '?' : Math.round(bpm * 10) / 10} BPM`,
    m.loop ? `${m.loop.bars}마디 반복` : '반복 없음',
    duration(m.length_s),
    m.vocal ? '보컬' : '연주곡',
  ].join(' · ')
}

const STRETCH_REASON: Record<string, string> = {
  'no grid': '모델 격자 없음',
  'uneven grid': '격자가 고르지 않음',
  'larger than the canvas': '캔버스보다 큼',
  empty: '빈 그림',
}

/** How pixel art was fitted: "모델 픽셀 32px · 18×26칸 · 1배", or "늘려 맞춤 (격자가 고르지 않음)". */
export function pixelFitText(fit: PixelFit | undefined): string {
  if (!fit) return ''
  const cell = fit.cell_px
    ? `${fit.cell_px[0] === fit.cell_px[1] ? fit.cell_px[0] : fit.cell_px.join('×')}px`
    : undefined
  const blocks = fit.native_size ? `${fit.native_size.join('×')}칸` : undefined
  if (fit.fit === 'native') return `모델 픽셀 ${cell} · ${blocks} · ${fit.scale}배`
  const reason = STRETCH_REASON[fit.reason ?? ''] ?? fit.reason
  const found = cell && blocks ? `, 모델 픽셀 ${cell} · ${blocks}` : ''
  return `늘려 맞춤 (${reason}${found})`
}

export const KIND_LABEL: Record<string, string> = {
  sprite: '스프라이트',
  icon: '아이콘',
  bgm: 'BGM',
  animation: '애니메이션',
  page_image: '쪽 그림',
  book_export: '책 내보내기',
}

export const PAGE_STATUS_LABEL: Record<PageStatus, string> = {
  draft: '준비',
  queued: '생성 중',
  candidate: '검수 대기',
  approved: '채택',
  redo: '재작업 요청',
}

/** A book's jobs are reviewed in the book, page by page, not in the project's job list. */
export function isBookJob(job: Pick<Job, 'kind'>): boolean {
  return job.kind === 'page_image' || job.kind === 'book_export'
}

/** What a job makes: an image kind (sprite, icon) from its params, or the job kind (bgm). */
export function jobKind(job: Pick<Job, 'kind' | 'params'>): string {
  return job.params.kind ?? job.kind
}

export function jobKindLabel(job: Pick<Job, 'kind' | 'params'>): string {
  return KIND_LABEL[jobKind(job)] ?? jobKind(job)
}

/** The request in words: an image's description or a song's brief. */
export function jobTitle(job: Pick<Job, 'params'>): string {
  return job.params.description ?? job.params.brief ?? '(설명 없음)'
}

export const JOB_STATUS_LABEL: Record<string, string> = {
  queued: '대기',
  running: '생성 중',
  done: '완료',
  failed: '실패',
  cancelled: '취소됨',
}

const STAGE_LABEL: Record<string, string> = {
  starting: '시작 중',
  'starting ComfyUI': 'ComfyUI 켜는 중',
  'encoding prompt': '프롬프트 인코딩',
  'uploading reference': '참고 이미지 올리는 중',
  'uploading references': '참고 이미지 올리는 중',
  generating: '생성 중',
  'laying out': '조판 중',
  'freeing memory': '메모리 비우는 중',
  // animations (sprite-gen + codex)
  preparing: 'sprite-gen 준비 중',
  'generating rows (codex)': '줄 생성 중(codex)',
  'extracting frames': '프레임 추출 중',
}

/** Korean label for a job stage from the backend ("generating 2/4" -> "생성 2/4"; an animation's
 * "generating rows (codex) 1/2" -> "줄 생성 중(codex) 1/2"). */
export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return '시작 중'
  const step = stage.match(/^(generating|postprocess) (\d+\/\d+)$/)
  if (step) return `${step[1] === 'generating' ? '생성' : '후처리'} ${step[2]}`
  const of = stage.match(/^(.+) (\d+\/\d+)$/)
  if (of && STAGE_LABEL[of[1]]) return `${STAGE_LABEL[of[1]]} ${of[2]}`
  return STAGE_LABEL[stage] ?? stage
}

export type FrameRange = 'all' | 'idle' | 'walk'

/** The frames an animation plays for `range`, in order, with each frame's time: 'all' plays every tag. */
export function playOrder(tags: AnimationTag[] | undefined, range: FrameRange): { index: number; ms: number }[] {
  return (tags ?? [])
    .filter((tag) => range === 'all' || tag.name === range)
    .flatMap((tag) =>
      Array.from({ length: tag.to - tag.from + 1 }, (_, i) => ({ index: tag.from + i, ms: Math.round(tag.duration * 1000) })),
    )
}

export const TAG_LABEL: Record<string, string> = { idle: '대기', walk: '이동' }

export function frameNo(index: number): string {
  return String(index + 1).padStart(2, '0')
}

/** An MCP request line that recreates a candidate (or a whole job) in Claude Code. */
export function mcpRequest(job: Pick<Job, 'project' | 'params'>, asset?: Pick<Asset, 'seed'>): string {
  const p = job.params
  const seed = asset?.seed ?? p.seed
  const quote = (text: string) => `"${text.replace(/"/g, '\\"')}"`
  if (p.asset_id !== undefined) return `generate_animation(asset_id="${p.asset_id}", count=${asset ? 1 : (p.count ?? 1)})`
  if (p.brief !== undefined) {
    const songs = [
      `project="${job.project}"`,
      `brief=${quote(p.brief)}`,
      `bpm=${p.bpm}`,
      `seconds=${p.seconds ?? 90}`,
      `loop=${p.loop === false ? 'false' : 'true'}`,
      ...(p.vocal ? ['vocal=true', `lyrics=${quote(p.lyrics ?? '')}`] : [`keyscale="${p.keyscale ?? 'A minor'}"`]),
      `count=${asset ? 1 : (p.count ?? 2)}`,
      ...(seed != null ? [`seed=${seed}`] : []),
    ]
    return `generate_bgm(${songs.join(', ')})`
  }
  const args = [
    `project="${job.project}"`,
    `kind="${p.kind ?? 'sprite'}"`,
    `description="${(p.description ?? '').replace(/"/g, '\\"')}"`,
    `count=${asset ? 1 : (p.count ?? 4)}`,
    ...(seed != null ? [`seed=${seed}`] : []),
  ]
  return `generate_image(${args.join(', ')})`
}

/** The `claude mcp add` line for this checkout (`repoDir` from /api/status; a placeholder until it is known). */
export function mcpAddCommand(repoDir: string | undefined): string {
  const dir = !repoDir ? '<AIAssetStudio 폴더>' : /\s/.test(repoDir) ? `"${repoDir}"` : repoDir
  return `claude mcp add --transport stdio aiassetstudio --scope user -- uv --directory ${dir} run python -m aiassetstudio mcp`
}
