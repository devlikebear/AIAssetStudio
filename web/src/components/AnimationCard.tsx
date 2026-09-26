import { type CSSProperties, useState } from 'react'

import type { Asset, AssetStatus } from '../api'
import { type FrameRange, frameNo, TAG_LABEL } from '../format'
import { useFramePlayer, useWholeZoom } from '../hooks'
import { PencilMark } from './CandidateCard'

const stagger = (index: number) => ({ '--i': index }) as CSSProperties

function cellOf(asset: Asset): [number, number] {
  return asset.meta.animation?.cell ?? [32, 32]
}

interface FrameProps {
  asset: Asset
  frame: number
  zoom: number
  feetLine?: boolean
}

/** One frame of an animation, `zoom` times its size: a window on the row image (every frame side by side), moved by
 * whole pixels, so pixel art stays crisp and even. */
export function AnimationFrame({ asset, frame, zoom, feetLine = false }: FrameProps) {
  const [w, h] = cellOf(asset)
  const frames = asset.meta.animation?.frames ?? 10
  const ground = asset.meta.fit?.ground_row
  return (
    <div
      className="frame-anim"
      role="img"
      aria-label={`${asset.meta.description ?? '애니메이션'} · 프레임 ${frame}`}
      style={{
        width: w * zoom,
        height: h * zoom,
        backgroundImage: `url(${asset.files.row})`,
        backgroundSize: `${frames * w * zoom}px ${h * zoom}px`,
        backgroundPosition: `${-frame * w * zoom}px 0`,
      }}
    >
      {feetLine && ground != null && <span className="feet-line" style={{ top: (ground + 1) * zoom }} aria-hidden />}
    </div>
  )
}

interface CardProps {
  asset: Asset
  index: number
  onOpen: (asset: Asset) => void
  onSetStatus: (asset: Asset, status: AssetStatus) => void
}

/** An animation candidate: plays idle then walk in the game's timing, at a whole zoom. */
export function AnimationCard({ asset, index, onOpen, onSetStatus }: CardProps) {
  const [w, h] = cellOf(asset)
  const [plate, zoom] = useWholeZoom<HTMLButtonElement>(w, h)
  const frame = useFramePlayer(asset.meta.animation?.tags, 'all', true)
  const toggle = (status: AssetStatus) => onSetStatus(asset, asset.status === status ? 'candidate' : status)
  const fit = asset.meta.fit

  return (
    <figure className={`frame is-anim is-${asset.status}`} style={stagger(index)}>
      <button
        ref={plate}
        type="button"
        className="frame-plate checker"
        onClick={() => onOpen(asset)}
        aria-label={`애니메이션 ${frameNo(index)} 자세히 보기`}
      >
        <AnimationFrame asset={asset} frame={frame} zoom={zoom} />
        <PencilMark key={asset.status} status={asset.status} />
      </button>
      <figcaption className="frame-rebate">
        <span className="frame-no">{frameNo(index)}</span>
        <span className="frame-seed frame-tags">
          <span className="tag" title="codex(클라우드)로 만듦">
            codex
          </span>
          {fit && !fit.size_ok && (
            <span className="tag tag-warn" title="대기 프레임이 기본 스프라이트와 크기가 다릅니다">
              크기 다름
            </span>
          )}
        </span>
        <span className="frame-actions">
          <button
            type="button"
            className={`chip chip-select${asset.status === 'selected' ? ' is-on' : ''}`}
            aria-pressed={asset.status === 'selected'}
            onClick={() => toggle('selected')}
          >
            고르기
          </button>
          <button
            type="button"
            className={`chip chip-reject${asset.status === 'rejected' ? ' is-on' : ''}`}
            aria-pressed={asset.status === 'rejected'}
            onClick={() => toggle('rejected')}
          >
            버리기
          </button>
        </span>
      </figcaption>
    </figure>
  )
}

const RANGES: [FrameRange, string][] = [
  ['all', '전체'],
  ['idle', '대기'],
  ['walk', '이동'],
]
const ZOOMS = ['fit', 1, 2, 4] as const
type Zoom = (typeof ZOOMS)[number]

/** The detail view of an animation: play a range (all, idle, walk) or see every frame side by side. */
export function AnimationStage({ asset }: { asset: Asset }) {
  const [view, setView] = useState<'play' | 'frames'>('play')
  const [range, setRange] = useState<FrameRange>('all')
  const [playing, setPlaying] = useState(true)
  const [zoom, setZoom] = useState<Zoom>('fit')
  const [feetLine, setFeetLine] = useState(false)
  const [w, h] = cellOf(asset)
  const tags = asset.meta.animation?.tags ?? []
  const frames = asset.meta.animation?.frames ?? 10
  const frame = useFramePlayer(tags, range, playing)
  const [canvas, fitZoom] = useWholeZoom<HTMLDivElement>(w, h)
  // Frames view: 10 frames and their gaps across the canvas (about 12% more than the frames themselves).
  const [strip, stripZoom] = useWholeZoom<HTMLDivElement>(Math.ceil(frames * w * 1.12), h + 8)
  const scale = zoom === 'fit' ? fitZoom : zoom

  return (
    <>
      <div className="detail-toolbar">
        <div className="segmented" role="group" aria-label="보기">
          <button type="button" aria-pressed={view === 'play'} onClick={() => setView('play')}>
            재생
          </button>
          <button type="button" aria-pressed={view === 'frames'} onClick={() => setView('frames')}>
            프레임
          </button>
        </div>
        {view === 'play' && (
          <>
            <div className="segmented" role="group" aria-label="재생 범위">
              {RANGES.map(([r, label]) => (
                <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>
                  {label}
                </button>
              ))}
            </div>
            <button type="button" className="btn btn-ghost" onClick={() => setPlaying(!playing)}>
              {playing ? '멈춤' : '다시 재생'}
            </button>
            <div className="segmented" role="group" aria-label="확대">
              {ZOOMS.map((z) => (
                <button key={z} type="button" aria-pressed={zoom === z} onClick={() => setZoom(z)}>
                  {z === 'fit' ? '맞춤' : `${z}×`}
                </button>
              ))}
            </div>
          </>
        )}
        <button
          type="button"
          className="btn btn-ghost"
          aria-pressed={feetLine}
          onClick={() => setFeetLine(!feetLine)}
          title="발이 서는 줄 아래에 선을 긋습니다"
        >
          발 줄
        </button>
        <span className="detail-size">
          {w}×{h}
          {view === 'play' ? ` · 프레임 ${String(frame).padStart(3, '0')} · ${scale}×` : ` · ${stripZoom}×`}
        </span>
      </div>
      {view === 'play' ? (
        <div ref={canvas} className="detail-canvas checker">
          <AnimationFrame asset={asset} frame={frame} zoom={scale} feetLine={feetLine} />
          <PencilMark key={asset.status} status={asset.status} />
        </div>
      ) : (
        <div ref={strip} className="detail-canvas checker anim-frames">
          {tags.map((tag) => (
            <div key={tag.name} className="anim-tag" role="group" aria-label={TAG_LABEL[tag.name] ?? tag.name}>
              <p className="anim-tag-name">
                {TAG_LABEL[tag.name] ?? tag.name} · {Math.round(tag.duration * 1000)}ms
              </p>
              <div className="anim-tag-frames">
                {Array.from({ length: tag.to - tag.from + 1 }, (_, i) => tag.from + i).map((index) => (
                  <figure key={index} className="anim-cell">
                    <AnimationFrame asset={asset} frame={index} zoom={stripZoom} feetLine={feetLine} />
                    <figcaption>{String(index).padStart(3, '0')}</figcaption>
                  </figure>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
