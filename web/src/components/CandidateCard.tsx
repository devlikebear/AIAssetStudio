import { type CSSProperties, useState } from 'react'

import type { Asset, AssetStatus } from '../api'
import { frameNo } from '../format'
import { useWholeZoom } from '../hooks'

const stagger = (index: number) => ({ '--i': index }) as CSSProperties

interface Props {
  asset: Asset
  index: number
  onOpen: (asset: Asset) => void
  onSetStatus: (asset: Asset, status: AssetStatus) => void
}

/** Grease-pencil marks, drawn the way a photographer marks frames on a contact sheet. */
export function PencilMark({ status }: { status: AssetStatus }) {
  if (status === 'selected') {
    return (
      <svg className="mark mark-select" viewBox="0 0 100 100" aria-hidden>
        <path pathLength={1} d="M52 7 C 80 6, 95 26, 93 50 C 91 78, 70 94, 46 93 C 20 92, 6 72, 8 48 C 10 22, 30 8, 58 10" />
      </svg>
    )
  }
  if (status === 'rejected') {
    return (
      <svg className="mark mark-reject" viewBox="0 0 100 100" aria-hidden>
        <path pathLength={1} d="M14 16 C 38 40, 62 62, 87 86" />
        <path pathLength={1} d="M86 13 C 62 38, 40 60, 13 88" />
      </svg>
    )
  }
  return null
}

export function CandidateCard({ asset, index, onOpen, onSetStatus }: Props) {
  const [broken, setBroken] = useState(false)
  // Pixel art: the logical-size file, enlarged by a whole factor so every pixel is the same size.
  const pixel = asset.meta.pixel
  const [plate, zoom] = useWholeZoom<HTMLButtonElement>(pixel?.width, pixel?.height)
  const toggle = (status: AssetStatus) => onSetStatus(asset, asset.status === status ? 'candidate' : status)

  return (
    <figure className={`frame is-${asset.status}`} style={stagger(index)}>
      <button
        ref={plate}
        type="button"
        className="frame-plate checker"
        onClick={() => onOpen(asset)}
        aria-label={`후보 ${frameNo(index)} 자세히 보기`}
      >
        {broken ? (
          <span className="frame-missing">파일을 읽을 수 없음</span>
        ) : (
          <img
            src={pixel ? asset.files.processed : (asset.files.preview ?? asset.files.processed)}
            alt={asset.meta.description ?? ''}
            className={pixel ? 'pixelated is-whole' : undefined}
            style={pixel ? { width: pixel.width * zoom, height: pixel.height * zoom } : undefined}
            loading="lazy"
            onError={() => setBroken(true)}
          />
        )}
        <PencilMark key={asset.status} status={asset.status} />
      </button>
      <figcaption className="frame-rebate">
        <span className="frame-no">{frameNo(index)}</span>
        <span className="frame-seed">{asset.seed ?? '—'}</span>
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

export function PlaceholderFrame({ index, label, wide = false }: { index: number; label: string; wide?: boolean }) {
  return (
    <figure className={`frame is-pending${wide ? ' is-audio' : ''}`} style={stagger(index)} aria-label={label}>
      <div className="frame-plate checker">
        <span className="frame-developing">{label}</span>
      </div>
      <figcaption className="frame-rebate">
        <span className="frame-no">{frameNo(index)}</span>
        <span className="frame-seed">······</span>
      </figcaption>
    </figure>
  )
}
