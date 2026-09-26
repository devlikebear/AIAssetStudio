import type { ApiError, Status } from '../api'

interface Props {
  status: Status | undefined
  error: ApiError | undefined
  onRetry: () => void
}

export function StatusBanner({ status, error, onRetry }: Props) {
  let title: string | null = null
  let detail: string | null = null

  if (error) {
    title = '백엔드에 연결할 수 없습니다'
    detail =
      '터미널에서 uv run aiassetstudio serve 로 켜거나, Claude Code에서 에셋 스튜디오 도구를 부르면 자동으로 켜집니다.'
  } else if (status && !status.comfy.up) {
    title = 'ComfyUI가 꺼져 있습니다'
    detail = status.comfy.error ?? '다음 생성 요청 때 백엔드가 자동으로 켭니다(최대 2분).'
  } else if (status) {
    const missing = Object.entries(status.preflight)
      .filter(([, s]) => !s.ok && !s.reason)
      .map(([family, s]) => `${family}: ${[...s.missing_nodes, ...s.missing_models].join(', ')}`)
    if (missing.length) {
      title = '필요한 노드나 모델이 없습니다'
      detail = missing.join(' / ')
    }
  }

  if (!title) return null
  return (
    <div className="banner" role="alert">
      <span className="banner-lamp" aria-hidden />
      <div className="banner-text">
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
      <button type="button" className="btn btn-ghost" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  )
}
