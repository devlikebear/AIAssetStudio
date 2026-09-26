import { useEffect, useRef, useState } from 'react'

import { type Asset, type AssetMeta, type AssetStatus, exportAsset, type Job } from '../api'
import { duration, frameNo, KIND_LABEL, mcpRequest, pixelFitText, timeAgo } from '../format'
import { useWholeZoom } from '../hooks'
import { AnimationStage } from './AnimationCard'
import { SongPlayer } from './AudioCard'
import { PencilMark } from './CandidateCard'
import { CopyButton } from './CopyButton'

interface Props {
  asset: Asset
  job: Job | undefined
  siblings: Asset[] // candidates of the same job, in frame order
  exportDir: string | null
  onClose: () => void
  onNavigate: (asset: Asset) => void
  onSetStatus: (asset: Asset, status: AssetStatus) => void
  onChanged: () => void
}

type View = 'processed' | 'raw'
const ZOOMS = ['fit', 1, 2, 4] as const
type Zoom = (typeof ZOOMS)[number]

function percent(value: number | undefined) {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`
}

const MAX_WARNINGS = 3

function sizeText(size: [number, number] | undefined) {
  return size ? `${size[0]}×${size[1]}` : '?'
}

/** "프레임 32×32 · 발 28번째 줄 · 사용 색 5/12" and the idle / walk sizes against the base sprite. */
function animationSpec(meta: AssetMeta): string {
  const anim = meta.animation
  const fit = meta.fit
  if (!anim || !fit) return '—'
  const colors = anim.max_colors ? `${fit.colors_used}/${anim.max_colors}` : `${fit.colors_used}`
  const sizes = `대기 ${sizeText(fit.idle_size)} · 이동 ${sizeText(fit.walk_size)} · 기본 ${sizeText(fit.base_size)}`
  return [
    `프레임 ${anim.cell[0]}×${anim.cell[1]} × ${anim.frames} · 발 ${fit.ground_row}번째 줄 · 사용 색 ${colors} (기본 그림의 색)`,
    `${sizes}${fit.size_ok ? '' : ' · 크기 다름'}`,
  ].join('\n')
}

/** The warnings worth reading first: the studio's own, then sprite-gen's, at most MAX_WARNINGS and a count. */
function animationWarnings(meta: AssetMeta): string | undefined {
  const all = [...(meta.fit?.warnings ?? []), ...(meta.spritegen?.warnings ?? [])]
  if (meta.spritegen?.inspect?.ok === false) all.unshift(...(meta.spritegen.inspect.errors ?? []))
  if (!all.length) return undefined
  const more = all.length > MAX_WARNINGS ? `\n외 ${all.length - MAX_WARNINGS}개` : ''
  return all.slice(0, MAX_WARNINGS).join('\n') + more
}

export function DetailModal({
  asset,
  job,
  siblings,
  exportDir,
  onClose,
  onNavigate,
  onSetStatus,
  onChanged,
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [view, setView] = useState<View>('processed')
  const [zoom, setZoom] = useState<Zoom>('fit')
  const [name, setName] = useState('')
  const [exporting, setExporting] = useState(false)
  // Tied to the asset (and view) they were made for, so moving to another candidate shows a clean slate.
  const [exportResult, setExportResult] = useState<{ assetId: string; ok: boolean; text: string }>()
  const [brokenImage, setBrokenImage] = useState<string>()
  const imageKey = `${asset.id}-${view}`
  const broken = brokenImage === imageKey
  const shownExport = exportResult?.assetId === asset.id ? exportResult : undefined
  const index = siblings.findIndex((a) => a.id === asset.id)
  const prev = index > 0 ? siblings[index - 1] : undefined
  const next = index >= 0 && index < siblings.length - 1 ? siblings[index + 1] : undefined
  const meta = asset.meta
  const size = view === 'raw' ? meta.size_raw : meta.size_processed
  // Pixel art at "fit": the largest whole zoom that fits, so every pixel is the same size.
  const pixelView = Boolean(meta.pixel) && view === 'processed'
  const [canvas, fitZoom] = useWholeZoom<HTMLDivElement>(pixelView ? size?.[0] : undefined, size?.[1])
  const scale = zoom === 'fit' ? (pixelView ? fitZoom : undefined) : zoom
  const song = asset.kind === 'bgm'
  const anim = asset.kind === 'animation'

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT') return
      if (e.key === 'ArrowLeft' && prev) onNavigate(prev)
      if (e.key === 'ArrowRight' && next) onNavigate(next)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [prev, next, onNavigate])

  const toggle = (status: AssetStatus) => onSetStatus(asset, asset.status === status ? 'candidate' : status)

  const doExport = async () => {
    setExporting(true)
    try {
      const { paths } = await exportAsset(asset.id, name.trim() ? { name: name.trim() } : {})
      const files = anim ? `\n(한 줄 PNG, JSON, 폴더 안 프레임 PNG ${meta.animation?.frames ?? 10}장)` : ''
      setExportResult({ assetId: asset.id, ok: true, text: paths.join('\n') + files })
      onChanged()
    } catch (e) {
      setExportResult({ assetId: asset.id, ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setExporting(false)
    }
  }

  return (
    <dialog
      ref={dialog}
      className="detail"
      // Closing unmounts the component. Esc arrives as `cancel`; handle it directly instead of waiting for the
      // asynchronous `close` event, which a backgrounded window may not deliver promptly.
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && onClose()}
      aria-label="후보 상세"
    >
      <div className="detail-body">
        <div className="detail-stage">
          {song ? (
            <div className="detail-song">
              <SongPlayer key={asset.id} asset={asset} />
              {meta.vocal && meta.lyrics && <pre className="detail-lyrics">{meta.lyrics}</pre>}
            </div>
          ) : anim ? (
            <AnimationStage key={asset.id} asset={asset} />
          ) : (
            <>
          <div className="detail-toolbar">
            <div className="segmented" role="group" aria-label="보기">
              {(['processed', 'raw'] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>
                  {v === 'processed' ? '후처리본' : '원본'}
                </button>
              ))}
            </div>
            <div className="segmented" role="group" aria-label="확대">
              {ZOOMS.map((z) => (
                <button key={z} type="button" aria-pressed={zoom === z} onClick={() => setZoom(z)}>
                  {z === 'fit' ? '맞춤' : `${z}×`}
                </button>
              ))}
            </div>
            <span className="detail-size">
              {size ? `${size[0]}×${size[1]}` : ''}
              {scale && zoom === 'fit' ? ` · ${scale}×` : ''}
            </span>
          </div>
          <div ref={canvas} className={`detail-canvas checker${scale === undefined ? ' is-fit' : ''}`}>
            {broken ? (
              <div className="frame-missing">
                <p>파일을 읽을 수 없습니다. 기록은 오른쪽에 남아 있습니다.</p>
                {job && <CopyButton text={mcpRequest(job, asset)} label="같은 설정으로 다시 요청할 MCP 문장 복사" />}
              </div>
            ) : (
              <img
                key={imageKey}
                src={asset.files[view]}
                alt={meta.description ?? ''}
                className={pixelView || zoom !== 'fit' ? 'pixelated' : undefined}
                style={scale === undefined || !size ? undefined : { width: size[0] * scale, height: size[1] * scale }}
                onError={() => setBrokenImage(imageKey)}
              />
            )}
            <PencilMark key={asset.status} status={asset.status} />
          </div>
            </>
          )}
          <div className="detail-nav">
            <button type="button" className="btn btn-ghost" disabled={!prev} onClick={() => prev && onNavigate(prev)}>
              ← 이전
            </button>
            <span className="detail-frame">
              {frameNo(Math.max(index, 0))} / {frameNo(siblings.length - 1)}
            </span>
            <button type="button" className="btn btn-ghost" disabled={!next} onClick={() => next && onNavigate(next)}>
              다음 →
            </button>
          </div>
        </div>

        <aside className="detail-side">
          <header className="detail-head">
            <p className="detail-kicker">
              {KIND_LABEL[asset.kind] ?? asset.kind} · {asset.id} · {timeAgo(asset.created_at)}
            </p>
            <h2>{meta.description ?? '(설명 없음)'}</h2>
            <button type="button" className="icon-btn detail-close" onClick={onClose} aria-label="닫기">
              ×
            </button>
          </header>

          <div className="detail-actions">
            <button
              type="button"
              className={`btn btn-select${asset.status === 'selected' ? ' is-on' : ''}`}
              aria-pressed={asset.status === 'selected'}
              onClick={() => toggle('selected')}
            >
              {asset.status === 'selected' ? '고름 ✓' : '고르기'}
            </button>
            <button
              type="button"
              className={`btn btn-reject${asset.status === 'rejected' ? ' is-on' : ''}`}
              aria-pressed={asset.status === 'rejected'}
              onClick={() => toggle('rejected')}
            >
              {asset.status === 'rejected' ? '버림 ✕' : '버리기'}
            </button>
          </div>

          <form
            className="export"
            onSubmit={(e) => {
              e.preventDefault()
              doExport()
            }}
          >
            <label htmlFor="export-name">내보내기</label>
            <p className="export-dir">{exportDir ?? '프로젝트에 내보내기 폴더가 없습니다 (MCP로 설정)'}</p>
            <div className="export-row">
              <input
                id="export-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="파일 이름 (선택, 영문 소문자·숫자·_·-)"
                autoComplete="off"
              />
              <button type="submit" className="btn btn-primary" disabled={exporting || !exportDir}>
                {exporting ? '복사 중…' : '내보내기'}
              </button>
            </div>
            {shownExport && (
              <pre className={`export-result${shownExport.ok ? '' : ' is-error'}`}>{shownExport.text}</pre>
            )}
          </form>

          <dl className="facts">
            {anim ? (
              <>
                <dt>기본</dt>
                <dd className="facts-base">
                  {asset.files.base && <img className="pixelated checker" src={asset.files.base} alt="기본 스프라이트" />}
                  <span className="mono">{meta.base_asset ?? '—'}</span>
                  {meta.base_asset && <CopyButton text={meta.base_asset} label="복사" />}
                </dd>
                <dt>규격</dt>
                <dd className="mono facts-small">{animationSpec(meta)}</dd>
                {animationWarnings(meta) && (
                  <>
                    <dt>경고</dt>
                    <dd className="mono facts-small">{animationWarnings(meta)}</dd>
                  </>
                )}
                <dt>만든 곳</dt>
                <dd className="facts-small">
                  {meta.cloud?.provider ?? 'codex'}(클라우드)로 만듦
                  {meta.spritegen?.version ? ` · sprite-gen ${meta.spritegen.version}` : ''}
                </dd>
              </>
            ) : (
              <>
                <dt>시드</dt>
                <dd className="mono">{asset.seed ?? '—'}</dd>
              </>
            )}
            {meta.pixel && (
              <>
                <dt>규격</dt>
                <dd className="mono facts-small">
                  논리 크기 {meta.pixel.width}×{meta.pixel.height} · 사용 색 {meta.pixel.colors_used}/
                  {meta.pixel.max_colors}
                  {meta.pixel.palette ? `
고정 팔레트 ${meta.pixel.palette.length}색` : ''}
                  {meta.pixel.fit ? `
${pixelFitText(meta.pixel.fit)}` : ''}
                </dd>
              </>
            )}
            {meta.reference && (
              <>
                <dt>참고</dt>
                <dd className="mono facts-small">참고 이미지 사용 ({meta.reference.mode})</dd>
              </>
            )}
            {anim ? null : song ? (
              <>
                <dt>곡</dt>
                <dd className="mono facts-small">
                  {meta.loop?.bpm && Math.abs(meta.loop.bpm - (meta.bpm ?? 0)) >= 0.05
                    ? `${meta.loop.bpm.toFixed(2)} BPM (요청 ${meta.bpm})`
                    : `${meta.bpm} BPM`}{' '}
                  · {meta.vocal ? '보컬 (YuE2)' : `연주곡 · ${meta.keyscale ?? ''}`}
                </dd>
                <dt>반복</dt>
                <dd className="mono facts-small">
                  {meta.loop
                    ? `${meta.loop.bars}마디, 원곡 ${meta.loop.start_s.toFixed(1)}–${meta.loop.end_s.toFixed(1)}초\n이음새 비율 ${meta.loop.seam_ratio} (1 이하면 급변 없음)`
                    : (meta.loop_error ?? '반복 없음')}
                </dd>
                <dt>길이</dt>
                <dd className="mono facts-small">
                  원본 {duration(meta.raw_s)} → 끝 무음 제거 {duration(meta.trimmed_s)} → {meta.loop ? '반복본' : '정리본'}{' '}
                  {duration(meta.length_s)}
                  {meta.ogg_error ? `\nOGG 없음: ${meta.ogg_error}` : ''}
                </dd>
                <dt>{meta.vocal ? '스타일' : '태그'}</dt>
                <dd className="facts-prompt">{meta.vocal ? meta.style : meta.tags}</dd>
              </>
            ) : (
              <>
                <dt>프롬프트</dt>
                <dd className="facts-prompt">{meta.prompt ?? '—'}</dd>
              </>
            )}
            {!anim && (
              <>
                <dt>모델</dt>
                <dd className="mono facts-small">
                  {meta.models ? Object.values(meta.models).join('\n') : '—'}
                  {meta.steps ? `\n${meta.steps} steps · ${meta.sampler ?? ''}` : ''}
                </dd>
              </>
            )}
            {!song && !anim && (
              <>
                <dt>알파</dt>
                <dd className="mono facts-small">
                  투명 {percent(meta.alpha_processed?.transparent)} · 불투명 {percent(meta.alpha_processed?.opaque)} ·
                  부분 {percent(meta.alpha_processed?.partial)}
                  {'\n'}테두리 평균 {meta.alpha_processed?.border_mean ?? '—'} (원본 {meta.alpha_raw?.border_mean ?? '—'})
                </dd>
              </>
            )}
            <dt>시간</dt>
            <dd className="mono facts-small">
              {meta.timings ? Object.entries(meta.timings).map(([k, v]) => `${k} ${v}s`).join(' · ') : '—'}
            </dd>
            {meta.exports && meta.exports.length > 0 && (
              <>
                <dt>내보낸 곳</dt>
                <dd className="mono facts-small">{meta.exports.map((x) => x.path).join('\n')}</dd>
              </>
            )}
          </dl>

          {job && (
            <p className="detail-foot">
              <CopyButton text={mcpRequest(job, asset)} label="같은 설정 복사 (MCP 요청 문장)" />
            </p>
          )}
        </aside>
      </div>
    </dialog>
  )
}
