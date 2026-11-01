import { useState } from 'react'

import type { ClipMethod, Page, PageStatus, updatePage } from '../api'
import { PAGE_STATUS_LABEL } from '../format'

type Fields = Parameters<typeof updatePage>[1]
type Tab = 'picture' | 'narration' | 'clip'

const CLIP_METHODS: [ClipMethod, string][] = [
  ['full', '클립 전체'],
  ['head', '앞부분만'],
  ['still', '그림만'],
]

interface Props {
  page: Page
  onChange: (page: Page, fields: Fields) => Promise<void>
}

/** One page: its picture and narration, each with its candidates and verdict, its words and where they come from. */
export function PageCard({ page, onChange }: Props) {
  const [tab, setTab] = useState<Tab>('picture')
  const chosen = page.candidates.find((c) => c.id === page.image_asset_id)
  const take = page.narration_candidates.find((c) => c.id === page.narration_asset_id)
  const sources = page.source_refs.map((r) => r.label || r.node_id)
  const busy = page.status === 'queued'
  const speaking = page.narration_status === 'queued'
  const animating = page.clip_status === 'queued'
  const clip = page.clip_candidates.find((c) => c.id === page.clip_asset_id)
  const status = { picture: page.status, narration: page.narration_status, clip: page.clip_status }[tab]

  return (
    <article className={`page-card is-${status}`}>
      <div className="page-plate">
        {tab === 'clip' && clip?.files.mp4 && page.clip_method !== 'still' ? (
          <video key={clip.id} src={clip.files.mp4} poster={clip.files.first} controls preload="none" />
        ) : chosen?.files.preview ? (
          <img src={chosen.files.preview} alt={`${page.number}쪽 그림`} />
        ) : (
          <span className="frame-missing">{busy ? '생성 중' : '그림 없음'}</span>
        )}
      </div>
      {tab === 'picture' && page.candidates.length > 1 && (
        <div className="page-candidates" role="group" aria-label={`${page.number}쪽 후보`}>
          {page.candidates.map((candidate, i) => (
            <button
              key={candidate.id}
              type="button"
              aria-pressed={candidate.id === page.image_asset_id}
              aria-label={`후보 ${i + 1}`}
              onClick={() => onChange(page, { image_asset_id: candidate.id })}
            >
              <img src={candidate.files.preview} alt="" />
            </button>
          ))}
        </div>
      )}
      <div className="page-body">
        <header className="page-head">
          <span className="page-number">{page.number}</span>
          <div className="segmented" role="group" aria-label={`${page.number}쪽 검수 대상`}>
            <button type="button" aria-pressed={tab === 'picture'} onClick={() => setTab('picture')}>
              그림
            </button>
            <button type="button" aria-pressed={tab === 'narration'} onClick={() => setTab('narration')}>
              낭독
            </button>
            <button type="button" aria-pressed={tab === 'clip'} onClick={() => setTab('clip')}>
              영상
            </button>
          </div>
        </header>
        <p className="page-text">{page.text || '본문 없음'}</p>
        <p className={sources.length ? 'page-source' : 'page-source is-missing'}>
          {sources.length ? `근거: ${sources.join(', ')}` : '근거 원문이 기록되지 않았습니다'}
        </p>
        {tab === 'picture' ? (
          <Verdict
            status={page.status}
            note={page.note}
            ready={Boolean(chosen)}
            busy={busy}
            onApprove={() => onChange(page, { status: 'approved' })}
            onRedo={(note) => onChange(page, { status: 'redo', note })}
          />
        ) : tab === 'clip' ? (
          <>
            <p className="page-source">움직임: {page.motion_prompt || '지시 없음'}</p>
            {clip?.files.last && page.clip_method !== 'still' && (
              <figure className="page-last-frame">
                <img src={clip.files.last} alt={`${page.number}쪽 클립 끝 프레임`} />
                <figcaption>끝 프레임. 클립이 끝나면 이 장면이 천천히 확대되며 남습니다.</figcaption>
              </figure>
            )}
            {page.clip_candidates.length > 1 && (
              <div className="segmented" role="group" aria-label={`${page.number}쪽 클립 후보`}>
                {page.clip_candidates.map((candidate, i) => (
                  <button
                    key={candidate.id}
                    type="button"
                    aria-pressed={candidate.id === page.clip_asset_id}
                    onClick={() => onChange(page, { clip_asset_id: candidate.id })}
                  >
                    후보 {i + 1}
                  </button>
                ))}
              </div>
            )}
            <div className="segmented" role="group" aria-label={`${page.number}쪽 표현 방식`}>
              {CLIP_METHODS.map(([method, label]) => (
                <button
                  key={method}
                  type="button"
                  aria-pressed={page.clip_method === method}
                  onClick={() => onChange(page, { clip_method: method })}
                >
                  {label}
                </button>
              ))}
            </div>
            {page.clip_method === 'head' && (
              <label className="page-head-seconds">
                앞부분 초
                <input
                  type="number"
                  min={0.5}
                  max={5}
                  step={0.5}
                  defaultValue={page.clip_head_s}
                  onBlur={(e) => onChange(page, { clip_head_s: Number(e.target.value) })}
                />
              </label>
            )}
            <Verdict
              status={page.clip_status}
              note={page.clip_note}
              ready={page.clip_method === 'still' ? Boolean(chosen) : Boolean(clip)}
              busy={animating}
              onApprove={() => onChange(page, { clip_status: 'approved' })}
              onRedo={(note) => onChange(page, { clip_status: 'redo', clip_note: note })}
            />
          </>
        ) : (
          <>
            {take?.files.wav ? (
              <audio key={take.id} className="page-audio" src={take.files.wav} controls preload="none" />
            ) : (
              <p className="frame-missing">{speaking ? '낭독 생성 중' : '낭독 없음'}</p>
            )}
            {page.narration_candidates.length > 1 && (
              <div className="segmented" role="group" aria-label={`${page.number}쪽 낭독 후보`}>
                {page.narration_candidates.map((candidate, i) => (
                  <button
                    key={candidate.id}
                    type="button"
                    aria-pressed={candidate.id === page.narration_asset_id}
                    onClick={() => onChange(page, { narration_asset_id: candidate.id })}
                  >
                    후보 {i + 1}
                  </button>
                ))}
              </div>
            )}
            <Verdict
              status={page.narration_status}
              note={page.narration_note}
              ready={Boolean(take)}
              busy={speaking}
              onApprove={() => onChange(page, { narration_status: 'approved' })}
              onRedo={(note) => onChange(page, { narration_status: 'redo', narration_note: note })}
            />
          </>
        )}
      </div>
    </article>
  )
}

interface VerdictProps {
  status: PageStatus
  note: string | null
  ready: boolean
  busy: boolean
  onApprove: () => void
  onRedo: (note: string) => Promise<void>
}

/** The person's verdict on a picture or a narration: approve it, or ask for a redo with a note for the agent. */
function Verdict({ status, note, ready, busy, onApprove, onRedo }: VerdictProps) {
  const [writing, setWriting] = useState(false)
  const [draft, setDraft] = useState('')

  const requestRedo = async () => {
    await onRedo(draft.trim())
    setWriting(false)
    setDraft('')
  }

  return (
    <>
      <span className={`status-pill page-status is-${status}`}>{PAGE_STATUS_LABEL[status]}</span>
      {note && <p className="page-note">재작업 메모: {note}</p>}
      {writing ? (
        <div className="page-redo">
          <label>
            무엇을 고칠까요
            <textarea value={draft} rows={3} onChange={(e) => setDraft(e.target.value)} autoFocus />
          </label>
          <div className="page-actions">
            <button type="button" className="btn btn-primary" disabled={!draft.trim()} onClick={requestRedo}>
              재작업 요청
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setWriting(false)}>
              취소
            </button>
          </div>
        </div>
      ) : (
        <div className="page-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!ready || busy || status === 'approved'}
            onClick={onApprove}
          >
            채택
          </button>
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setWriting(true)}>
            재작업 요청
          </button>
        </div>
      )}
    </>
  )
}
