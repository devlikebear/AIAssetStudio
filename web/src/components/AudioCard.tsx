import { type CSSProperties, useRef, useState } from 'react'

import type { Asset, AssetStatus } from '../api'
import { frameNo, playableFile, songSummary } from '../format'
import { PencilMark } from './CandidateCard'

const stagger = (index: number) => ({ '--i': index }) as CSSProperties

/** An audio player that loops the song, can switch to ComfyUI's original file, and can jump to the seam. */
export function SongPlayer({ asset }: { asset: Asset }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [source, setSource] = useState<'song' | 'raw'>('song')
  const [broken, setBroken] = useState<string>()
  const src = source === 'raw' ? asset.files.raw : playableFile(asset)

  // Start 3 s before the end: with `loop`, playback runs straight across the seam into the start.
  const listenToSeam = () => {
    const el = audio.current
    if (!el || !Number.isFinite(el.duration)) return
    el.currentTime = Math.max(0, el.duration - 3)
    void el.play()
  }

  return (
    <div className="song-player">
      {broken === src ? (
        <p className="frame-missing">파일을 읽을 수 없습니다</p>
      ) : (
        <audio key={src} ref={audio} src={src} controls loop preload="metadata" onError={() => setBroken(src)} />
      )}
      <div className="song-controls">
        <div className="segmented" role="group" aria-label="들을 파일">
          <button type="button" aria-pressed={source === 'song'} onClick={() => setSource('song')}>
            {asset.meta.loop ? '반복본' : '정리본'}
          </button>
          <button type="button" aria-pressed={source === 'raw'} onClick={() => setSource('raw')} disabled={!asset.files.raw}>
            원본
          </button>
        </div>
        <button
          type="button"
          className="btn btn-ghost song-seam"
          onClick={listenToSeam}
          disabled={source === 'raw' || !asset.meta.loop}
          title="끝나기 3초 전부터 재생해서 반복 지점을 들어 봅니다"
        >
          이음새 듣기
        </button>
      </div>
    </div>
  )
}

interface Props {
  asset: Asset
  index: number
  onOpen: (asset: Asset) => void
  onSetStatus: (asset: Asset, status: AssetStatus) => void
}

export function AudioCard({ asset, index, onOpen, onSetStatus }: Props) {
  const toggle = (status: AssetStatus) => onSetStatus(asset, asset.status === status ? 'candidate' : status)

  return (
    <figure className={`frame is-audio is-${asset.status}`} style={stagger(index)}>
      <div className="frame-plate song-plate">
        <button type="button" className="song-open" onClick={() => onOpen(asset)} aria-label={`곡 ${frameNo(index)} 자세히 보기`}>
          <span className="song-summary">{songSummary(asset)}</span>
          {asset.meta.loop_error && <span className="song-note">반복 구간을 못 만들어 전체 곡을 씁니다</span>}
        </button>
        <SongPlayer asset={asset} />
        <PencilMark key={asset.status} status={asset.status} />
      </div>
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
