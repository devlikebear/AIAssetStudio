import type { Asset, AssetStatus, Job } from '../api'
import { JOB_STATUS_LABEL, jobKindLabel, jobTitle, stageLabel, timeAgo } from '../format'
import { AnimationCard } from './AnimationCard'
import { AudioCard } from './AudioCard'
import { CandidateCard, PlaceholderFrame } from './CandidateCard'

interface Props {
  job: Job
  assets: Asset[] // after filters
  made: number // candidates finished so far, before filters
  highlighted: boolean
  onOpen: (asset: Asset) => void
  onSetStatus: (asset: Asset, status: AssetStatus) => void
}

export function JobGroup({ job, assets, made, highlighted, onOpen, onSetStatus }: Props) {
  const count = job.params.count ?? made
  const active = job.status === 'queued' || job.status === 'running'
  const pending = active ? Math.max(0, count - made) : 0
  const kind = jobKindLabel(job)

  return (
    <section id={`job-${job.id}`} className={`strip is-${job.status}${highlighted ? ' is-highlighted' : ''}`}>
      <header className="strip-head">
        <span className="strip-id">JOB {job.id.slice(0, 6).toUpperCase()}</span>
        <h2 className="strip-title">{jobTitle(job)}</h2>
        <span className="strip-meta">
          {kind} × {count}
        </span>
        <time className="strip-meta" dateTime={job.created_at}>
          {timeAgo(job.created_at)}
        </time>
        <span className={`status-pill is-${job.status}`}>
          {job.status === 'running' ? stageLabel(job.stage) : JOB_STATUS_LABEL[job.status]}
        </span>
      </header>
      {job.error && <p className="strip-error">{job.error}</p>}
      <div className="frames">
        {assets.map((asset, i) => {
          const Card = asset.kind === 'bgm' ? AudioCard : asset.kind === 'animation' ? AnimationCard : CandidateCard
          return <Card key={asset.id} asset={asset} index={i} onOpen={onOpen} onSetStatus={onSetStatus} />
        })}
        {Array.from({ length: pending }, (_, i) => (
          <PlaceholderFrame
            key={`pending-${i}`}
            index={made + i}
            wide={job.kind === 'bgm'}
            label={job.status === 'queued' ? '대기' : i === 0 ? '생성 중' : '차례 대기'}
          />
        ))}
      </div>
    </section>
  )
}
