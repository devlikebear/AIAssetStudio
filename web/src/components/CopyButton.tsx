import { useState } from 'react'

export function CopyButton({ text, label = '복사' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      window.prompt('복사해서 쓰세요', text)
    }
  }
  return (
    <button type="button" className="link-btn" onClick={copy} title={text}>
      {copied ? '복사됨' : label}
    </button>
  )
}
