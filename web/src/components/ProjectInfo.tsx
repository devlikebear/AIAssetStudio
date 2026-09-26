import { useEffect, useRef } from 'react'

import { type Project, projectReferenceUrl, type Status } from '../api'
import { timeAgo } from '../format'

function specText(project: Project): string {
  if (!project.pixel_art) return '아님'
  const icon = project.icon_size ?? project.logical_width
  return `스프라이트 ${project.logical_width}×${project.logical_height} · 아이콘 ${icon}×${icon} · 최대 ${project.max_colors}색`
}

interface Props {
  project: Project
  animation: Status['animation'] // sprite-gen and codex readiness, from /api/status
  onClose: () => void
}

/** Read-only project preset. Editing happens through the MCP tools (create_project / update_project). */
export function ProjectInfo({ project, animation, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  // [label, value, monospace?]
  const rows: [string, string, boolean][] = [
    ['슬러그', project.slug, true],
    ['화풍 문구', project.style || '없음', false],
    ['내보내기 폴더', project.export_dir ?? '없음', Boolean(project.export_dir)],
    ['픽셀아트', specText(project), false],
  ]
  if (!project.pixel_art && project.icon_size) {
    rows.push(['아이콘 크기', `${project.icon_size}×${project.icon_size}`, false])
  }
  if (!project.reference_image) rows.push(['참고 이미지', '없음', false])
  if (project.animation_cloud) {
    const blocked = animation && !animation.ok ? `\n지금은 만들 수 없음: ${animation.reason ?? '준비되지 않음'}` : ''
    rows.push(['애니메이션', `클라우드(codex) 허용 — 스프라이트가 OpenAI로 전송됨${blocked}`, false])
  } else {
    rows.push(['애니메이션', '꺼짐 — Claude Code에서 update_project animation_cloud=true', false])
  }
  rows.push(['만든 때', timeAgo(project.created_at), false])

  return (
    <dialog
      ref={dialog}
      className="drawer"
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && onClose()}
      aria-label="프로젝트 정보"
    >
      <header className="drawer-head">
        <p className="detail-kicker">프로젝트</p>
        <h2>{project.name}</h2>
        <button type="button" className="icon-btn detail-close" onClick={onClose} aria-label="닫기">
          ×
        </button>
      </header>
      <dl className="facts">
        {rows.map(([label, value, mono]) => (
          <div key={label} className="facts-row">
            <dt>{label}</dt>
            <dd className={mono ? 'mono' : undefined}>{value}</dd>
          </div>
        ))}
      </dl>
      {project.palette && project.palette.length > 0 && (
        <div className="palette" aria-label="팔레트">
          {project.palette.map((color) => (
            <span key={color} className="swatch" style={{ background: color }} title={color} />
          ))}
        </div>
      )}
      {project.reference_image && (
        <figure className="reference">
          <img className="reference-img checker" src={projectReferenceUrl(project)} alt="참고 이미지" />
          <figcaption>
            참고 이미지 · 스프라이트에만 적용
            <span className="mono">{project.reference_image}</span>
          </figcaption>
        </figure>
      )}
      <p className="drawer-note">
        읽기 전용입니다. 바꾸려면 Claude Code에서 update_project로 요청하세요.
      </p>
    </dialog>
  )
}
