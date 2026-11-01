import { useState } from 'react'

import type { Page, updatePage } from '../api'
import { PAGE_STATUS_LABEL } from '../format'

interface Props {
  page: Page
  onChange: (page: Page, fields: Parameters<typeof updatePage>[1]) => Promise<void>
}

/** One page: its picture and candidates, its words and where they come from, and the person's verdict. */
export function PageCard({ page, onChange }: Props) {
  const [writing, setWriting] = useState(false)
  const [note, setNote] = useState('')
  const chosen = page.candidates.find((c) => c.id === page.image_asset_id)
  const sources = page.source_refs.map((r) => r.label || r.node_id)
  const busy = page.status === 'queued'

  const requestRedo = async () => {
    await onChange(page, { status: 'redo', note: note.trim() })
    setWriting(false)
    setNote('')
  }

  return (
    <article className={`page-card is-${page.status}`}>
      <div className="page-plate">
        {chosen?.files.preview ? (
          <img src={chosen.files.preview} alt={`${page.number}쪽 그림`} />
        ) : (
          <span className="frame-missing">{busy ? '생성 중' : '그림 없음'}</span>
        )}
      </div>
      {page.candidates.length > 1 && (
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
          <span className={`status-pill page-status is-${page.status}`}>{PAGE_STATUS_LABEL[page.status]}</span>
        </header>
        <p className="page-text">{page.text || '본문 없음'}</p>
        <p className={sources.length ? 'page-source' : 'page-source is-missing'}>
          {sources.length ? `근거: ${sources.join(', ')}` : '근거 원문이 기록되지 않았습니다'}
        </p>
        {page.note && <p className="page-note">재작업 메모: {page.note}</p>}
        {writing ? (
          <div className="page-redo">
            <label>
              무엇을 고칠까요
              <textarea value={note} rows={3} onChange={(e) => setNote(e.target.value)} autoFocus />
            </label>
            <div className="page-actions">
              <button type="button" className="btn btn-primary" disabled={!note.trim()} onClick={requestRedo}>
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
              disabled={!chosen || busy || page.status === 'approved'}
              onClick={() => onChange(page, { status: 'approved' })}
            >
              채택
            </button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setWriting(true)}>
              재작업 요청
            </button>
          </div>
        )}
      </div>
    </article>
  )
}
