import { useCallback, useState } from 'react'

import { animateBook, type Asset, exportBook, getBook, getPack, listAssets, narrateBook, type Page, updatePage } from '../api'
import { usePoll } from '../hooks'
import { PageCard } from './PageCard'

const SPEECH_PACK = 'speech-ko'
const SHEET_KIND = { character: '인물', place: '장소', prop: '소품' }
const LICENSE_NOTE: Record<string, string> = {
  research_only: '연구·평가 목적으로 제한된 모델로 만든 그림이 있습니다. 공유하거나 판매하기 전에 라이선스를 확인하세요.',
  unknown: '라이선스를 확인하지 못한 모델로 만든 그림이 있습니다. 공유하거나 판매하기 전에 확인하세요.',
}

interface Props {
  bookId: string
  onError: (message: string | undefined) => void
}

/** A book: every page side by side with its words, so a person can judge the whole and leave notes for the agent. */
export function BookView({ bookId, onError }: Props) {
  const book = usePoll(() => getBook(bookId), 3000, `book:${bookId}`)
  const project = book.data?.project
  const exports = usePoll(
    project ? () => listAssets({ project, kind: 'book_export' }) : null,
    5000,
    `exports:${project ?? ''}`,
  )
  const [exporting, setExporting] = useState(false)
  const [narrating, setNarrating] = useState(false)
  const [animating, setAnimating] = useState(false)
  const speech = usePoll(() => getPack(SPEECH_PACK), 10000, 'speech-pack')

  const change = useCallback(
    async (page: Page, fields: Parameters<typeof updatePage>[1]) => {
      try {
        await updatePage(page.id, fields)
        onError(undefined)
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e))
      }
      book.refresh()
    },
    [book, onError],
  )

  const startNarration = async () => {
    setNarrating(true)
    try {
      await narrateBook(bookId)
      onError(undefined)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
    setNarrating(false)
    book.refresh()
  }

  const startClips = async () => {
    setAnimating(true)
    try {
      await animateBook(bookId)
      onError(undefined)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
    setAnimating(false)
    book.refresh()
  }

  const startExport = async (allowDraft: boolean, format: 'pdf' | 'mp3' | 'mp4' = 'pdf') => {
    setExporting(true)
    try {
      await exportBook(bookId, allowDraft, format)
      onError(undefined)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
    setExporting(false)
    exports.refresh()
  }

  if (book.error) return <p className="sheet-empty">이 책을 찾을 수 없습니다.</p>
  const data = book.data
  if (!data) return <p className="sheet-empty">불러오는 중</p>

  const approved = data.counts.approved ?? 0
  const total = data.pages.length
  const waiting = data.pages.filter((page) => page.status === 'candidate' && page.image_asset_id)
  const spoken = data.narration_counts.approved ?? 0
  const waitingTakes = data.pages.filter((page) => page.narration_status === 'candidate' && page.narration_asset_id)
  const toNarrate = data.pages.filter((p) => p.text && (p.narration_status === 'draft' || p.narration_status === 'redo'))
  const speechReady = speech.data?.status === 'installed'
  const shown = data.clip_counts.approved ?? 0
  const waitingClips = data.pages.filter((page) => page.clip_status === 'candidate' && page.clip_asset_id)
  const toAnimate = data.pages.filter(
    (p) => p.status === 'approved' && p.motion_prompt && p.clip_method !== 'still' && (p.clip_status === 'draft' || p.clip_status === 'redo'),
  )
  const videoReady = spoken === total && shown === total
  const licenseNote = data.license_class ? LICENSE_NOTE[data.license_class] : undefined
  const files = (exports.data ?? []).filter((a: Asset) => a.meta.book_id === bookId).reverse()

  return (
    <section className="book">
      <header className="book-head">
        <a className="link-btn" href={`#/p/${encodeURIComponent(data.project)}`}>
          프로젝트로
        </a>
        <h1>{data.title}</h1>
        <div className="book-tracks">
          <div className="book-track">
            <p className="book-progress">
              그림 {total}쪽 중 {approved}쪽 채택
              {progressNote(total, approved, 'PDF')}
            </p>
            <div className="page-actions">
              <ApproveAll
                pages={waiting}
                fields={{ status: 'approved' }}
                label="그림"
                onDone={book.refresh}
                onError={onError}
              />
              <button type="button" className="btn btn-primary" disabled={exporting || total === 0 || approved < total} onClick={() => startExport(false)}>
                PDF 내보내기
              </button>
              <button type="button" className="btn btn-ghost" disabled={exporting || total === 0} onClick={() => startExport(true)}>
                검수용 PDF
              </button>
            </div>
          </div>
          <div className="book-track">
            <p className="book-progress">
              낭독 {total}쪽 중 {spoken}쪽 채택
              {progressNote(total, spoken, 'MP3')}
            </p>
            <div className="page-actions">
              {speechReady ? (
                <button type="button" className="btn btn-ghost" disabled={narrating || toNarrate.length === 0} onClick={startNarration}>
                  낭독 {toNarrate.length}쪽 만들기
                </button>
              ) : (
                <a className="btn btn-ghost" href={`#/packs/${SPEECH_PACK}`}>
                  음성 팩 설치
                </a>
              )}
              <ApproveAll
                pages={waitingTakes}
                fields={{ narration_status: 'approved' }}
                label="낭독"
                onDone={book.refresh}
                onError={onError}
              />
              <button type="button" className="btn btn-primary" disabled={exporting || total === 0 || spoken < total} onClick={() => startExport(false, 'mp3')}>
                MP3 내보내기
              </button>
              <button type="button" className="btn btn-ghost" disabled={exporting || !data.pages.some((p) => p.narration_asset_id)} onClick={() => startExport(true, 'mp3')}>
                검수용 MP3
              </button>
            </div>
          </div>
          <div className="book-track">
            <p className="book-progress">
              영상 {total}쪽 중 {shown}쪽 채택
              {total > 0 && (videoReady ? ' · MP4를 내보낼 수 있습니다' : ' · 낭독과 영상을 모두 채택해야 MP4를 내보낼 수 있습니다')}
            </p>
            <div className="page-actions">
              <button type="button" className="btn btn-ghost" disabled={animating || toAnimate.length === 0} onClick={startClips}>
                클립 {toAnimate.length}쪽 만들기
              </button>
              <ApproveAll
                pages={waitingClips}
                fields={{ clip_status: 'approved' }}
                label="영상"
                onDone={book.refresh}
                onError={onError}
              />
              <button type="button" className="btn btn-primary" disabled={exporting || total === 0 || !videoReady} onClick={() => startExport(false, 'mp4')}>
                MP4 내보내기
              </button>
              <button type="button" className="btn btn-ghost" disabled={exporting || !data.pages.some((p) => p.narration_asset_id)} onClick={() => startExport(true, 'mp4')}>
                검수용 MP4
              </button>
            </div>
          </div>
        </div>
      </header>

      {licenseNote && (
        <div className="banner banner-soft" role="status">
          <div className="banner-text">
            <strong>라이선스 확인 필요</strong>
            <span>{licenseNote}</span>
          </div>
        </div>
      )}

      {files.length > 0 && (
        <ul className="book-exports" aria-label="내보낸 파일">
          {files.slice(0, 3).map((file) => (
            <li key={file.id}>
              <a href={file.files.pdf ?? file.files.mp3 ?? file.files.mp4} target="_blank" rel="noreferrer">
                {file.files.pdf ? 'PDF' : file.files.mp3 ? 'MP3' : 'MP4'} {new Date(file.created_at).toLocaleString('ko-KR')}
              </a>
              {/* License warnings are in the banner above; what remains is about the layout. */}
              {(file.meta.warnings as string[] | undefined)
                ?.filter((warning) => !warning.startsWith('license:'))
                .map((warning) => (
                  <span key={warning}>{warning}</span>
                ))}
            </li>
          ))}
        </ul>
      )}

      {data.sheets.length > 0 && (
        <ul className="book-sheets" aria-label="시트">
          {data.sheets.map((sheet) => (
            <li key={sheet.id} title={sheet.description}>
              {sheet.asset?.files.preview && <img src={sheet.asset.files.preview} alt="" />}
              <span>
                {SHEET_KIND[sheet.kind]} · {sheet.name}
              </span>
            </li>
          ))}
        </ul>
      )}

      {total === 0 && <p className="sheet-empty">아직 쪽이 없습니다. 에이전트가 쪽 대본을 넣으면 여기에 나타납니다.</p>}
      <div className="page-grid">
        {data.pages.map((page) => (
          <PageCard key={page.id} page={page} onChange={change} />
        ))}
      </div>
    </section>
  )
}

function progressNote(total: number, approved: number, format: string): string {
  if (total === 0) return ''
  return approved < total ? ` · 남은 ${total - approved}쪽을 모두 채택해야 ${format}를 내보낼 수 있습니다` : ` · ${format}를 내보낼 수 있습니다`
}

interface ApproveAllProps {
  pages: Page[]
  fields: Parameters<typeof updatePage>[1]
  label: string
  onDone: () => void
  onError: (message: string | undefined) => void
}

/** Approve every page waiting for review, after a second click. Pages with a redo request stay as they are. */
function ApproveAll({ pages, fields, label, onDone, onError }: ApproveAllProps) {
  const [confirming, setConfirming] = useState(false)
  const [approving, setApproving] = useState(false)

  // Page by page, as the single button does; a failure stops here and leaves the rest waiting.
  const approve = async () => {
    setConfirming(false)
    setApproving(true)
    try {
      for (const page of pages) await updatePage(page.id, fields)
      onError(undefined)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
    setApproving(false)
    onDone()
  }

  if (pages.length === 0) return null
  if (confirming) {
    return (
      <>
        <button type="button" className="btn btn-primary" onClick={approve}>
          {label} {pages.length}쪽 채택 확인
        </button>
        <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)}>
          취소
        </button>
      </>
    )
  }
  return (
    <button type="button" className="btn btn-ghost" disabled={approving} onClick={() => setConfirming(true)}>
      {label} 검수 대기 {pages.length}쪽 모두 채택
    </button>
  )
}
