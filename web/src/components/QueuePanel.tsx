import type { Job, Status } from '../api'
import { duration, JOB_STATUS_LABEL, jobKindLabel, jobTitle, mcpRequest, stageLabel, timeAgo } from '../format'
import { CopyButton } from './CopyButton'

interface Props {
  status: Status | undefined
  active: Job[] | undefined
  failed: Job[] | undefined // recent failures only
  onCancel: (job: Job) => void
  onOpenJob: (job: Job) => void
}

export function QueuePanel({ status, active, failed, onCancel, onOpenJob }: Props) {
  const current = status?.queue.current
  const running = active?.find((j) => j.status === 'running')
  const queued = (active ?? []).filter((j) => j.status === 'queued').reverse() // oldest first
  const recentFailures = failed ?? []

  return (
    <aside className="queue" aria-label="대기열">
      <h2 className="queue-title">대기열</h2>

      {running ? (
        <div className="queue-now">
          <span className="queue-lamp" aria-hidden />
          <button type="button" className="queue-job" onClick={() => onOpenJob(running)}>
            <span className="queue-job-title">{jobTitle(running)}</span>
            <span className="queue-job-meta">
              {running.project} · {jobKindLabel(running)} ×{running.params.count}
            </span>
            <span className="queue-job-stage">
              {current?.id === running.id ? `${stageLabel(current.stage)} · ${duration(current.elapsed_s)}` : '생성 중'}
            </span>
          </button>
          <button type="button" className="btn btn-danger btn-small" onClick={() => onCancel(running)}>
            취소
          </button>
        </div>
      ) : (
        <p className="queue-empty">{queued.length ? '곧 시작합니다' : '대기 중인 작업 없음'}</p>
      )}

      {queued.length > 0 && (
        <ol className="queue-list">
          {queued.map((job) => (
            <li key={job.id}>
              <button type="button" className="queue-job" onClick={() => onOpenJob(job)}>
                <span className="queue-job-title">{jobTitle(job)}</span>
                <span className="queue-job-meta">
                  {job.project} · {JOB_STATUS_LABEL[job.status]} · {timeAgo(job.created_at)}
                </span>
              </button>
              <button type="button" className="btn btn-ghost btn-small" onClick={() => onCancel(job)}>
                취소
              </button>
            </li>
          ))}
        </ol>
      )}

      {recentFailures.length > 0 && (
        <>
          <h3 className="queue-subtitle">최근 실패</h3>
          <ul className="queue-failures">
            {recentFailures.map((job) => (
              <li key={job.id}>
                <button type="button" className="queue-job" onClick={() => onOpenJob(job)}>
                  <span className="queue-job-title">{jobTitle(job)}</span>
                  <span className="queue-job-meta">
                    {job.project} · {timeAgo(job.finished_at)}
                  </span>
                </button>
                <p className="queue-error">{job.error}</p>
                <CopyButton text={mcpRequest(job)} label="다시 요청할 MCP 문장 복사" />
              </li>
            ))}
          </ul>
        </>
      )}

      {status?.comfy.up && (
        <p className="queue-foot">
          VRAM 여유 {Math.round((status.comfy.vram_free_mb ?? 0) / 1024)} GB · RAM 여유{' '}
          {Math.round((status.comfy.ram_free_mb ?? 0) / 1024)} GB
        </p>
      )}
    </aside>
  )
}
