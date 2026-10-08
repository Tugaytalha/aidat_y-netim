import { Badge, Group, Text, Tooltip } from '@mantine/core'
import type { ReactNode } from 'react'
import type { Candidate, Txn } from '../api'
import { SIGNAL_LABELS } from '../format'

const TR: Record<string, string> = { İ: 'i', I: 'i', ı: 'i', Ş: 's', ş: 's', Ğ: 'g', ğ: 'g', Ü: 'u', ü: 'u', Ö: 'o', ö: 'o', Ç: 'c', ç: 'c' }

/** Sunucudaki fold() ile aynı: harf harf eşleme yaptığı için indeksler orijinal metinle örtüşür. */
export function fold(s: string): string {
  return Array.from(s)
    .map((c) => TR[c] ?? c.toLowerCase())
    .join('')
}

/** Eşleştirme motorunun bulduğu daire ifadelerini açıklamada işaretler. */
export function HighlightedDescription({ txn }: { txn: Txn }) {
  const text = txn.description
  const folded = fold(text).replace(/\s+/g, ' ')
  const normText = text.replace(/\s+/g, ' ')
  const ranges: { start: number; end: number; strong: boolean }[] = []
  for (const h of txn.highlights ?? []) {
    const needle = h.text.replace(/#/g, '')
    if (!needle.trim()) continue
    const idx = folded.indexOf(needle)
    if (idx >= 0) ranges.push({ start: idx, end: idx + needle.length, strong: h.strength === 'strong' || h.strength === 'normal' })
  }
  ranges.sort((a, b) => a.start - b.start)
  const parts: ReactNode[] = []
  let pos = 0
  ranges.forEach((r, i) => {
    if (r.start < pos) return
    parts.push(normText.slice(pos, r.start))
    parts.push(
      <mark key={i} className={r.strong ? 'hl-strong' : 'hl-weak'}>
        {normText.slice(r.start, r.end)}
      </mark>,
    )
    pos = r.end
  })
  parts.push(normText.slice(pos))
  return (
    <Text size="sm" style={{ wordBreak: 'break-word' }}>
      {parts}
    </Text>
  )
}

export function CandidateSignals({ c }: { c: Candidate }) {
  return (
    <Group gap={4}>
      {c.signals.map((s, i) => (
        <Tooltip key={i} label={s.detail} withArrow multiline maw={320}>
          <Badge size="xs" variant={s.weight >= 0.85 ? 'filled' : 'light'} color={s.weight > 0.5 ? 'teal' : 'gray'}>
            {SIGNAL_LABELS[s.kind] ?? s.kind} {Math.round(s.weight * 100)}
          </Badge>
        </Tooltip>
      ))}
    </Group>
  )
}
