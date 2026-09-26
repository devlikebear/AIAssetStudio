import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  type Asset,
  type AssetStatus,
  cancelJob,
  getJob,
  getStatus,
  type Job,
  listAssets,
  listJobs,
  listProjects,
  setAssetStatus,
} from './api'
import { CopyButton } from './components/CopyButton'
import { DetailModal } from './components/DetailModal'
import { JobGroup } from './components/JobGroup'
import { ProjectInfo } from './components/ProjectInfo'
import { QueuePanel } from './components/QueuePanel'
import { StatusBanner } from './components/StatusBanner'
import { jobKind, KIND_LABEL, mcpAddCommand } from './format'
import { useHashRoute, usePoll, useStoredState } from './hooks'
import './App.css'

type KindFilter = 'all' | 'sprite' | 'icon' | 'bgm' | 'animation'
type StatusFilter = 'all' | AssetStatus
type Checker = 'dark' | 'light'

const DAY_MS = 24 * 3600 * 1000

/** Failed jobs from the last 24 hours, newest first, at most 5 (for the queue panel). */
function recentFailures(jobs: Job[]): Job[] {
  const since = Date.now() - DAY_MS
  return jobs.filter((j) => j.finished_at && new Date(j.finished_at).getTime() > since).slice(0, 5)
}

const STATUS_FILTERS: [StatusFilter, string][] = [
  ['all', '전체'],
  ['candidate', '후보'],
  ['selected', '고름'],
  ['rejected', '버림'],
]

export default function App() {
  const [route, navigate] = useHashRoute()
  const [kind, setKind] = useState<KindFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [checker, setChecker] = useStoredState<Checker>('aiassetstudio.checker', 'dark')
  const [openAssetId, setOpenAssetId] = useState<string>()
  const [jobProject, setJobProject] = useState<{ jobId: string; project: string }>()
  const [actionError, setActionError] = useState<string>()

  const status = usePoll(getStatus, 5000, 'status')
  const projects = usePoll(listProjects, 10000, 'projects')
  const active = usePoll(() => listJobs({ status: 'active' }), 2000, 'active')
  const failed = usePoll(() => listJobs({ status: 'failed' }).then(recentFailures), 10000, 'failed')

  // #/jobs/<id>: find the job's project, then show that project with the job highlighted.
  useEffect(() => {
    if (!route.jobId || jobProject?.jobId === route.jobId) return
    getJob(route.jobId)
      .then((job) => setJobProject({ jobId: job.id, project: job.project }))
      .catch(() => setJobProject(undefined))
  }, [route.jobId, jobProject?.jobId])

  const slug =
    route.project ??
    (route.jobId && jobProject?.jobId === route.jobId ? jobProject.project : undefined) ??
    projects.data?.[0]?.slug
  const project = projects.data?.find((p) => p.slug === slug)

  const sheet = usePoll(
    slug ? () => Promise.all([listJobs({ project: slug }), listAssets({ project: slug })]) : null,
    3000,
    `sheet:${slug ?? ''}`,
  )
  const [jobs, assets] = sheet.data ?? [undefined, undefined]

  const assetsByJob = useMemo(() => {
    const byJob = new Map<string, Asset[]>()
    for (const asset of assets ?? []) byJob.set(asset.job_id, [...(byJob.get(asset.job_id) ?? []), asset])
    return byJob
  }, [assets])

  const visible = (asset: Asset) =>
    (kind === 'all' || asset.kind === kind) && (statusFilter === 'all' || asset.status === statusFilter)

  const shownJobs = (jobs ?? []).filter((job) => {
    const all = assetsByJob.get(job.id) ?? []
    if (kind !== 'all' && jobKind(job) !== kind) return false
    if (statusFilter === 'all') return true
    return all.some(visible)
  })

  // Scroll to the job from #/jobs/<id> once its group is on the page (once, not on every poll).
  const highlightId = route.jobId
  const scrolledTo = useRef<string>(undefined)
  useEffect(() => {
    if (!highlightId || scrolledTo.current === highlightId || !jobs?.some((j) => j.id === highlightId)) return
    scrolledTo.current = highlightId
    // Instant: a smooth scroll needs animation frames, which a backgrounded window may not run.
    document.getElementById(`job-${highlightId}`)?.scrollIntoView({ block: 'start' })
  }, [highlightId, jobs])

  const openAsset = assets?.find((a) => a.id === openAssetId)
  const openJob = jobs?.find((j) => j.id === openAsset?.job_id)

  const refreshAll = useCallback(() => {
    sheet.refresh()
    active.refresh()
  }, [sheet, active])

  const updateStatus = useCallback(
    async (asset: Asset, next: AssetStatus) => {
      try {
        await setAssetStatus(asset.id, next)
        setActionError(undefined)
      } catch (e) {
        setActionError(e instanceof Error ? e.message : String(e))
      }
      sheet.refresh()
    },
    [sheet],
  )

  const cancel = useCallback(
    async (job: Job) => {
      try {
        await cancelJob(job.id)
      } catch (e) {
        setActionError(e instanceof Error ? e.message : String(e))
      }
      refreshAll()
    },
    [refreshAll],
  )

  const retry = () => {
    status.refresh()
    projects.refresh()
    refreshAll()
  }

  return (
    <div className="app" data-checker={checker}>
      <header className="topbar">
        <a className="wordmark" href="#/" aria-label="AIAssetStudio 갤러리">
          <span className="wordmark-lamp" aria-hidden />
          AI ASSET STUDIO
        </a>

        {projects.data && projects.data.length > 0 && (
          <div className="project-picker">
            <select
              aria-label="프로젝트"
              value={slug ?? ''}
              onChange={(e) => navigate(`#/p/${encodeURIComponent(e.target.value)}`)}
            >
              {projects.data.map((p) => (
                <option key={p.slug} value={p.slug}>
                  {p.name}
                </option>
              ))}
            </select>
            {project && (
              <button type="button" className="link-btn" onClick={() => navigate(`#/p/${project.slug}/info`)}>
                프로젝트 정보
              </button>
            )}
          </div>
        )}

        <div className="filters">
          <div className="segmented" role="group" aria-label="종류">
            {(['all', 'sprite', 'icon', 'bgm', 'animation'] as KindFilter[]).map((k) => (
              <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>
                {k === 'all' ? '모든 종류' : KIND_LABEL[k]}
              </button>
            ))}
          </div>
          <div className="segmented" role="group" aria-label="상태">
            {STATUS_FILTERS.map(([s, label]) => (
              <button key={s} type="button" aria-pressed={statusFilter === s} onClick={() => setStatusFilter(s)}>
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="checker-toggle"
            onClick={() => setChecker(checker === 'dark' ? 'light' : 'dark')}
            aria-label={`체크무늬 ${checker === 'dark' ? '밝게' : '어둡게'}`}
            title="투명 배경 체크무늬 밝기"
          >
            <span className="checker checker-swatch" aria-hidden />
          </button>
        </div>
      </header>

      <StatusBanner status={status.data} error={status.error} onRetry={retry} />
      {actionError && (
        <div className="banner banner-soft" role="status">
          <div className="banner-text">
            <strong>요청이 실패했습니다</strong>
            <span>{actionError}</span>
          </div>
          <button type="button" className="btn btn-ghost" onClick={() => setActionError(undefined)}>
            닫기
          </button>
        </div>
      )}

      <div className="layout">
        <main className="sheet">
          {projects.data && projects.data.length === 0 && <NoProjects repoDir={status.data?.repo_dir} />}
          {project && jobs && jobs.length === 0 && <NoAssets projectName={project.name} />}
          {project && jobs && jobs.length > 0 && shownJobs.length === 0 && (
            <p className="sheet-empty">이 필터에 맞는 후보가 없습니다.</p>
          )}
          {shownJobs.map((job) => {
            const all = assetsByJob.get(job.id) ?? []
            return (
              <JobGroup
                key={job.id}
                job={job}
                assets={all.filter(visible)}
                made={all.length}
                highlighted={job.id === highlightId}
                onOpen={(a) => setOpenAssetId(a.id)}
                onSetStatus={updateStatus}
              />
            )
          })}
        </main>

        <QueuePanel
          status={status.data}
          active={active.data}
          failed={failed.data}
          onCancel={cancel}
          onOpenJob={(job) => navigate(`#/jobs/${job.id}`)}
        />
      </div>

      {openAsset && (
        <DetailModal
          asset={openAsset}
          job={openJob}
          siblings={(assetsByJob.get(openAsset.job_id) ?? []).filter(visible)}
          exportDir={project?.export_dir ?? null}
          onClose={() => setOpenAssetId(undefined)}
          onNavigate={(a) => setOpenAssetId(a.id)}
          onSetStatus={updateStatus}
          onChanged={sheet.refresh}
        />
      )}
      {route.info && project && (
        <ProjectInfo
          project={project}
          animation={status.data?.animation}
          onClose={() => navigate(`#/p/${project.slug}`)}
        />
      )}
    </div>
  )
}

function NoProjects({ repoDir }: { repoDir?: string }) {
  const command = mcpAddCommand(repoDir)
  return (
    <section className="empty">
      <p className="empty-kicker">빈 인화지</p>
      <h1>아직 프로젝트가 없습니다</h1>
      <p>게임 작업 중인 Claude Code 세션에서 이렇게 요청해 보세요.</p>
      <blockquote>“에셋 스튜디오에 LAST LIGHT 프로젝트 만들어줘. 어두운 판타지 화풍, 내보내기 폴더는 …”</blockquote>
      <p>MCP 서버를 아직 등록하지 않았다면 먼저 이 명령을 한 번 실행합니다.</p>
      <pre className="command">{command}</pre>
      <CopyButton text={command} label="등록 명령 복사" />
    </section>
  )
}

function NoAssets({ projectName }: { projectName: string }) {
  return (
    <section className="empty">
      <p className="empty-kicker">빈 인화지</p>
      <h1>{projectName}에는 아직 뽑은 에셋이 없습니다</h1>
      <p>Claude Code에서 이런 식으로 요청하면 후보가 여기에 나타납니다.</p>
      <ul className="examples">
        <li>“이 프로젝트 화풍으로 슬라임 스프라이트 4장 뽑아줘”</li>
        <li>“칼 아이콘 4장 만들어서 미리보기 보여줘”</li>
        <li>“고른 거 게임의 Art 폴더로 내보내줘”</li>
      </ul>
    </section>
  )
}
