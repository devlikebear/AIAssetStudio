import { useCallback, useEffect, useRef, useState } from 'react'

import { type AnimationTag, ApiError } from './api'
import { type FrameRange, playOrder } from './format'

export interface Polled<T> {
  data: T | undefined
  error: ApiError | undefined
  refresh: () => void
}

/** Calls `load` now, then every `intervalMs` while the tab is visible. `key` restarts it (e.g. another project).
 * The first load runs even in a background tab, so a gallery link opened in the background is ready when shown. */
export function usePoll<T>(load: (() => Promise<T>) | null, intervalMs: number, key: string): Polled<T> {
  // Results remember which key they belong to, so switching projects never shows the previous project's data.
  const [result, setResult] = useState<{ key: string; data?: T; error?: ApiError }>({ key })
  const [tick, setTick] = useState(0)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    let first = true
    const run = async () => {
      const current = loadRef.current
      if (current && (first || document.visibilityState === 'visible')) {
        first = false
        try {
          const value = await current()
          if (!cancelled) setResult({ key, data: value })
        } catch (e) {
          if (!cancelled) {
            const error = e instanceof ApiError ? e : new ApiError(0, String(e))
            setResult((prev) => ({ key, data: prev.key === key ? prev.data : undefined, error }))
          }
        }
      }
      if (!cancelled) timer = window.setTimeout(run, intervalMs)
    }
    run()
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        window.clearTimeout(timer)
        run()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [key, intervalMs, tick])

  const refresh = useCallback(() => setTick((t) => t + 1), [])
  const current = result.key === key ? result : undefined
  return { data: current?.data, error: current?.error, refresh }
}

/** The largest whole zoom (at least 1) at which a `width` x `height` image fits the content box of the element the
 * returned ref is attached to. Pixel art scaled by a whole factor keeps every pixel the same size. */
export function useWholeZoom<E extends HTMLElement>(width: number | undefined, height: number | undefined) {
  const [zoom, setZoom] = useState(1)
  // A callback ref measures as soon as the element is attached, and once more right after the effects of that
  // render (a <dialog> gets its size only when an effect calls showModal()). ResizeObserver alone reports at the
  // next rendering step, which a background tab or a hidden preview pane may not reach, leaving pixel art at 1x.
  const ref = useCallback(
    (element: E | null) => {
      if (!element || !width || !height) return
      const measure = () => {
        const style = getComputedStyle(element)
        const w = element.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
        const h = element.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)
        if (w > 0 && h > 0) setZoom(Math.max(1, Math.floor(Math.min(w / width, h / height))))
      }
      measure()
      const timer = window.setTimeout(measure, 0)
      const observer = new ResizeObserver(measure)
      observer.observe(element)
      return () => {
        window.clearTimeout(timer)
        observer.disconnect()
      }
    },
    [width, height],
  )
  return [ref, zoom] as const
}

/** The frame an animation shows now: steps through `range` of its tags at each frame's own time, from the first
 * frame of the range, looping while `playing`. One setTimeout at a time. A hidden tab may slow the timer; that only
 * slows the preview. */
export function useFramePlayer(tags: AnimationTag[] | undefined, range: FrameRange, playing: boolean): number {
  const order = playOrder(tags, range)
  // Primitives only in the effect's inputs: the gallery polls new asset objects every few seconds, and a timer
  // restarted on each poll would stutter.
  const key = order.map((f) => `${f.index}:${f.ms}`).join(',')
  const [position, setPosition] = useState({ key, step: 0 })
  const step = position.key === key && position.step < order.length ? position.step : 0
  const count = order.length
  const ms = order[step]?.ms ?? 0
  useEffect(() => {
    if (!playing || count < 2) return
    const timer = window.setTimeout(() => setPosition({ key, step: (step + 1) % count }), ms)
    return () => window.clearTimeout(timer)
  }, [playing, key, step, count, ms])
  return order[step]?.index ?? 0
}

export type Route = { project?: string; jobId?: string; bookId?: string; info: boolean }

function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (parts[0] === 'p' && parts[1]) return { project: parts[1], info: parts[2] === 'info' }
  if (parts[0] === 'jobs' && parts[1]) return { jobId: parts[1], info: false }
  if (parts[0] === 'books' && parts[1]) return { bookId: parts[1], info: false }
  return { info: false }
}

/** Hash routes: #/p/<slug>, #/p/<slug>/info, #/jobs/<id>, #/books/<id>. No server-side routing needed. */
export function useHashRoute(): [Route, (hash: string) => void] {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const navigate = useCallback((hash: string) => {
    window.location.hash = hash
  }, [])
  return [route, navigate]
}

/** A preference kept in localStorage; falls back to memory when storage is unavailable. */
export function useStoredState<T extends string>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return (window.localStorage.getItem(key) as T | null) ?? initial
    } catch {
      return initial
    }
  })
  const update = useCallback(
    (next: T) => {
      setValue(next)
      try {
        window.localStorage.setItem(key, next)
      } catch {
        // storage blocked: keep it for this session only
      }
    },
    [key],
  )
  return [value, update]
}
