import { useState } from 'react'

import { acceptPack, cancelPack, installPack, listPacks, type Pack, removePack } from '../api'
import { usePoll } from '../hooks'

const FEATURE_LABEL: Record<string, string> = { audiobook: '오디오북' }
const STATUS_LABEL: Record<string, string> = {
  not_installed: '설치 안 됨',
  installing: '설치 중',
  installed: '설치됨',
  failed: '설치 실패',
  cancelled: '설치 취소됨',
}

interface Props {
  packId?: string
  onError: (message: string | undefined) => void
}

/** Feature packs: what each brings, what it asks a person to agree to, and its install. Agreeing happens only here. */
export function PacksView({ packId, onError }: Props) {
  const packs = usePoll(listPacks, 2000, 'packs')

  if (packs.error && !packs.data) return <p className="sheet-empty">기능 팩을 불러올 수 없습니다.</p>
  if (!packs.data) return <p className="sheet-empty">불러오는 중</p>
  const shown = packId ? packs.data.filter((pack) => pack.id === packId) : packs.data

  return (
    <section className="packs">
      <header className="book-head">
        {packId && (
          <a className="link-btn" href="#/packs">
            모든 기능 팩
          </a>
        )}
        <h1>기능 팩</h1>
      </header>
      {shown.length === 0 && <p className="sheet-empty">이 기능 팩을 찾을 수 없습니다.</p>}
      {shown.map((pack) => (
        <PackCard key={pack.id} pack={pack} onError={onError} onChanged={packs.refresh} />
      ))}
    </section>
  )
}

function PackCard({ pack, onError, onChanged }: { pack: Pack; onError: Props['onError']; onChanged: () => void }) {
  const [ticked, setTicked] = useState<string[]>([])
  const [removing, setRemoving] = useState(false)
  const [busy, setBusy] = useState(false)
  const waiting = pack.licenses.filter((license) => !license.accepted)
  const allAgreed = waiting.every((license) => ticked.includes(license.id))
  const newlyAgreed = waiting.filter((license) => ticked.includes(license.id)).map((license) => license.id)
  const installing = pack.status === 'installing'
  const canRemove = pack.status === 'installed' || pack.status === 'failed' || pack.status === 'cancelled'

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      onError(undefined)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
    setBusy(false)
    onChanged()
  }

  const agree = () => act(() => acceptPack(pack.id, newlyAgreed))
  const install = () =>
    act(async () => {
      if (newlyAgreed.length) await acceptPack(pack.id, newlyAgreed)
      await installPack(pack.id)
    })
  const remove = () => {
    setRemoving(false)
    return act(() => removePack(pack.id))
  }

  return (
    <article className="pack-card">
      <header className="pack-head">
        <h2>{pack.title}</h2>
        <span className={`status-pill pack-status is-${pack.status}`}>{STATUS_LABEL[pack.status] ?? pack.status}</span>
      </header>
      <dl className="pack-facts">
        <dt>기능</dt>
        <dd>{FEATURE_LABEL[pack.feature] ?? pack.feature}</dd>
        <dt>버전</dt>
        <dd>{pack.version}</dd>
        <dt>내려받기</dt>
        <dd>{(pack.download_size / 2 ** 30).toFixed(1)} GB</dd>
        <dt>필요한 빈 디스크</dt>
        <dd>{pack.tested.disk_gb} GB</dd>
        <dt>시험 사양</dt>
        <dd>
          VRAM {pack.tested.vram_gb} GB, RAM {pack.tested.ram_gb} GB, {pack.tested.os}
        </dd>
      </dl>

      {pack.license_changed && (
        <div className="banner banner-soft" role="alert">
          <div className="banner-text">
            <strong>라이선스가 바뀌었습니다</strong>
            <span>동의한 원문과 지금 원문이 달라 설치를 멈췄습니다. Studio가 새 원문을 확인할 때까지 설치할 수 없습니다.</span>
          </div>
        </div>
      )}

      <ul className="pack-licenses">
        {pack.licenses.map((license) => (
          <li key={license.id}>
            <label>
              <input
                type="checkbox"
                checked={license.accepted || ticked.includes(license.id)}
                disabled={license.accepted}
                onChange={(e) =>
                  setTicked(e.target.checked ? [...ticked, license.id] : ticked.filter((id) => id !== license.id))
                }
              />
              <span>{license.name}에 동의합니다</span>
            </label>
            <a href={license.url} target="_blank" rel="noreferrer">
              원문 읽기
            </a>
            <p>{license.summary_ko}</p>
          </li>
        ))}
      </ul>

      {pack.stage && <p className="pack-stage">{pack.stage}</p>}
      {pack.error && !pack.license_changed && <p className="pack-error">{pack.error}</p>}

      <div className="page-actions">
        {pack.status !== 'installed' && !installing && (
          <>
            <button type="button" className="btn btn-primary" disabled={busy || !allAgreed} onClick={install}>
              {newlyAgreed.length ? '동의하고 설치' : '설치'}
            </button>
            {newlyAgreed.length > 0 && (
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={agree}>
                동의만 기록
              </button>
            )}
          </>
        )}
        {installing && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => act(() => cancelPack(pack.id))}>
            설치 취소
          </button>
        )}
        {canRemove &&
          (removing ? (
            <>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={remove}>
                삭제 확인
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setRemoving(false)}>
                그만두기
              </button>
            </>
          ) : (
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setRemoving(true)}>
              삭제
            </button>
          ))}
      </div>

      {pack.log_tail && (
        <details className="pack-log" open={pack.status === 'failed'}>
          <summary>설치 기록</summary>
          <pre>{pack.log_tail}</pre>
        </details>
      )}
    </article>
  )
}
