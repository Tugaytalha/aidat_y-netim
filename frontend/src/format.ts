import type { Money } from './api'

const tl = new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', minimumFractionDigits: 2 })
const tl0 = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 })

export const num = (v: Money | null | undefined): number => (v === null || v === undefined || v === '' ? 0 : Number(v))

export function money(v: Money | null | undefined): string {
  return tl.format(num(v))
}

/** Hücreler için kısa biçim: 3.600 */
export function moneyShort(v: Money | null | undefined): string {
  const n = num(v)
  return n === 0 ? '' : tl0.format(n)
}

const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara']

export function periodLabel(p: string | null | undefined, short = false): string {
  if (!p) return '—'
  const [y, m] = p.split('-')
  const names = short ? MONTHS_SHORT : MONTHS
  return `${names[Number(m) - 1]} ${short ? y.slice(2) : y}`
}

export function dateTR(d: string | null | undefined): string {
  if (!d) return '—'
  const [y, m, day] = d.slice(0, 10).split('-')
  return `${day}.${m}.${y}`
}

export function currentPeriod(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function addMonths(p: string, n: number): string {
  const [y, m] = p.split('-').map(Number)
  const idx = y * 12 + (m - 1) + n
  return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, '0')}`
}

export function periodOptions(from: string, to: string): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = []
  for (let p = to; p >= from; p = addMonths(p, -1)) out.push({ value: p, label: periodLabel(p) })
  return out
}

export const CATEGORY_LABELS: Record<string, string> = {
  aidat: 'Aidat',
  demirbas: 'Demirbaş',
  asansor: 'Asansör',
  ek_butce: 'Ek bütçe',
  diger: 'Diğer',
  devir: 'Devir',
  duzeltme: 'Düzeltme',
}

export const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  matched: { label: 'Eşleşti', color: 'teal' },
  suggested: { label: 'Öneri', color: 'yellow' },
  unmatched: { label: 'Eşleşmedi', color: 'red' },
  ignored: { label: 'Yok sayıldı', color: 'gray' },
}

export const METHOD_LABELS: Record<string, string> = {
  code: 'Daire kodu',
  alias: 'Gönderen hafızası',
  person: 'Sakin adı',
  manual: 'Elle',
  legacy: 'Eski Excel',
  llm: 'AI',
}

export const SIGNAL_LABELS: Record<string, string> = {
  alias: 'Hafıza',
  code: 'Kod',
  person: 'İsim',
  body_name: 'Açıklamada ad',
  amount: 'Tutar',
  block: 'Blok',
}
