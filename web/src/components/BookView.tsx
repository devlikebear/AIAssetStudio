import { useCallback, useState } from 'react'

import { type Asset, exportBook, getBook, listAssets, type Page, updatePage } from '../api'
import { usePoll } from '../hooks'
import { PageCard } from './PageCard'

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
  const [confirming, setConfirming] = useState(false)
  const [approving, setApproving] = useState(false)

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

  // Page by page, as the single button does; a failure stops here and leaves the rest waiting.
  const approveAll = async (pages: Page[]) => {
    setConfirming(false)
    setApproving(true)
    try {
      for (const page of pages) await updatePage(page.id, { status: 'approved' })
      onError(undefined)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
    setApproving(false)
    book.refresh()
  }

  const startExport = async (allowDraft: boolean) => {
    setExporting(true)
    try {
      await exportBook(bookId, allowDraft)
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
  const licenseNote = data.license_class ? LICENSE_NOTE[data.license_class] : undefined
  const files = (exports.data ?? []).filter((a: Asset) => a.meta.book_id === bookId).reverse()

  return (
    <section className="book">
      <header className="book-head">
        <a className="link-btn" href={`#/p/${encodeURIComponent(data.project)}`}>
          프로젝트로
        </a>
        <h1>{data.title}</h1>
        <p className="book-progress">
          {total}쪽 중 {approved}쪽 채택
          {total > 0 && (approved < total ? ` · 남은 ${total - approved}쪽을 모두 채택해야 PDF를 내보낼 수 있습니다` : ' · PDF를 내보낼 수 있습니다')}
        </p>
        <div className="page-actions">
          {confirming ? (
            <>
              <button type="button" className="btn btn-primary" onClick={() => approveAll(waiting)}>
                {waiting.length}쪽 채택 확인
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)}>
                취소
              </button>
            </>
          ) : (
            waiting.length > 0 && (
              <button type="button" className="btn btn-ghost" disabled={approving} onClick={() => setConfirming(true)}>
                검수 대기 {waiting.length}쪽 모두 채택
              </button>
            )
          )}
          <button type="button" className="btn btn-primary" disabled={exporting || total === 0 || approved < total} onClick={() => startExport(false)}>
            PDF 내보내기
          </button>
          <button type="button" className="btn btn-ghost" disabled={exporting || total === 0} onClick={() => startExport(true)}>
            검수용 PDF
          </button>
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
              <a href={file.files.pdf} target="_blank" rel="noreferrer">
                PDF {new Date(file.created_at).toLocaleString('ko-KR')}
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
