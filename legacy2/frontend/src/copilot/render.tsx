import type { ReactNode } from 'react'
import { hrefOf } from './links'

/**
 * The copilot's answer on screen: paragraphs, bullets, **bold**, `code`, and links. A link of the kind
 * [Кабинет 214](room:<id>) leads to the place in the system; an http(s) or /api/… link opens as it is.
 */
export function Answer({ text, building }: { text: string; building: string | null }) {
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const Tag = list.ordered ? 'ol' : 'ul'
    blocks.push(<Tag key={blocks.length} className={list.ordered ? 'list-decimal pl-5' : 'list-disc pl-5'}>
      {list.items.map((it, i) => <li key={i}>{inline(it, building)}</li>)}</Tag>)
    list = null
  }
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const number = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (bullet || number) {
      const ordered = !!number
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] } }
      list.items.push((bullet ?? number)![1])
      continue
    }
    flush()
    if (!line.trim()) continue
    const heading = /^#{1,4}\s+(.*)$/.exec(line)
    blocks.push(heading
      ? <p key={blocks.length} className="font-medium">{inline(heading[1], building)}</p>
      : <p key={blocks.length}>{inline(line, building)}</p>)
  }
  flush()
  return <div className="space-y-1.5 text-sm leading-relaxed break-words">{blocks}</div>
}

const LINK = /\[([^\]]+)\]\(([^)\s]+)\)/g
const EMPH = /(\*\*[^*]+\*\*|`[^`]+`)/g

function inline(text: string, building: string | null): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(LINK)) {
    if (m.index! > last) out.push(...emphasis(text.slice(last, m.index), out.length))
    const href = hrefOf(m[2], building)
    const external = !!href && /^https?:\/\//.test(href)
    out.push(href
      ? <a key={out.length} href={href} className="text-primary underline underline-offset-2" target={external ? '_blank' : undefined}
        rel={external ? 'noreferrer' : undefined} download={href.startsWith('/api/reports/') || undefined}>{m[1]}</a>
      : <span key={out.length}>{m[1]}</span>)
    last = m.index! + m[0].length
  }
  if (last < text.length) out.push(...emphasis(text.slice(last), out.length))
  return out
}

function emphasis(text: string, base: number): ReactNode[] {
  return text.split(EMPH).filter(Boolean).map((part, i) =>
    part.startsWith('**') ? <b key={base + i}>{part.slice(2, -2)}</b>
      : part.startsWith('`') ? <code key={base + i} className="rounded bg-muted px-1 text-xs">{part.slice(1, -1)}</code>
        : <span key={base + i}>{part}</span>)
}
