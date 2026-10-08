// API istemcisi: token yönetimi, hata mesajları, dosya yükleme/indirme.

const TOKEN_KEY = 'aidat_token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* depolama kapalıysa oturum bellekte kalmaz */
  }
}

export class ApiError extends Error {
  status: number
  data: unknown
  constructor(status: number, message: string, data: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === 'object' && 'detail' in data) {
    const d = (data as { detail: unknown }).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === 'object' && 'msg' in x ? String(x.msg) : String(x))).join(', ')
  }
  return fallback
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(method: string, url: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let payload: BodyInit | undefined
  if (body instanceof FormData || body instanceof URLSearchParams) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  void isForm
  const res = await fetch(url, { method, headers, body: payload })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized) onUnauthorized()
    throw new ApiError(res.status, errorMessage(data, `İstek başarısız (${res.status})`), data)
  }
  return data as T
}

export const api = {
  get: <T>(url: string, params?: Record<string, string | number | undefined | null>) => {
    const qs = params
      ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)])).toString()
      : ''
    return request<T>('GET', url + (qs === '?' ? '' : qs))
  },
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  patch: <T>(url: string, body: unknown) => request<T>('PATCH', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
  upload: <T>(url: string, file: File, fields: Record<string, string | number | undefined | null> = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null && v !== '') fd.append(k, String(v))
    return request<T>('POST', url, fd)
  },
  login: (email: string, password: string) => {
    const body = new URLSearchParams({ username: email, password })
    return request<{ access_token: string; user: User }>('POST', '/api/auth/login', body)
  },
}

/** Yetkili istekle dosya indirir (Excel çıktıları). */
export async function download(url: string, fallbackName: string) {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
  if (!res.ok) throw new ApiError(res.status, 'Dosya indirilemedi', null)
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') ?? ''
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 5000)
}

// --- Tipler ---------------------------------------------------------------------------

export type Money = number | string

export interface User {
  id: number
  email: string
  full_name: string
  role: 'admin' | 'operator' | 'viewer'
  is_active: boolean
  site_ids: number[] | null
}

export interface SiteSummary {
  id: number
  name: string
  code: string
  address: string | null
  aidat_start_period: string | null
  legacy_cutoff_period: string | null
  llm_enabled: boolean
  auto_match_threshold: number | null
  notes: string | null
  unit_count?: number
}

export interface UnitBrief {
  id: number
  number: number
  code: string
  room_type: string | null
  area_m2: number | null
  aidat_start_period: string | null
}

export interface Block {
  id: number
  name: string
  aliases: string[]
  sort_order: number
  units: UnitBrief[]
}

export interface SiteDetail extends SiteSummary {
  bank_accounts: { id: number; iban: string; bank_name: string | null; account_no: string | null; branch: string | null }[]
  blocks: Block[]
}

export interface UnitRow {
  id: number
  code: string
  block: string
  block_id: number
  number: number
  room_type: string | null
  area_m2: number | null
  aidat_start_period: string | null
  notes: string | null
  legacy_tags: Record<string, unknown>
  people: { occupancy_id: number; person_id: number; name: string; role: string; is_primary: boolean }[]
  balance: Money
  charged: Money
  paid: Money
  overdue_months: number
}

export interface Signal {
  kind: string
  weight: number
  detail: string
}

export interface Candidate {
  unit_id: number
  code: string
  score: number
  signals: Signal[]
}

export interface Allocation {
  id: number
  unit_id: number
  code: string | null
  amount: Money
  category: string
  period: string
  method: string
  confidence: number | null
  confirmed_at: string | null
}

export interface Txn {
  id: number
  source: string
  txn_date: string
  receipt_no: string | null
  description: string
  amount: Money
  balance_after: Money | null
  status: 'unmatched' | 'suggested' | 'matched' | 'ignored'
  payer_name: string | null
  sender_bank: string | null
  channel: string | null
  category_hint: string | null
  stated_periods: string[]
  note: string | null
  allocations: Allocation[]
  candidates: Candidate[]
  split: { unit_id: number; amount: string }[] | null
  decision: string | null
  conflict: boolean
  reasons: string[]
  highlights: { text: string; strength: string }[]
  period_note: string | null
  llm: {
    unit_ids: number[]
    split: { unit_id: number; amount: string }[] | null
    category: string | null
    stated_periods: string[]
    confidence: number
    reason: string
    model: string
  } | null
}

export interface Page<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export interface Tariff {
  id: number
  scope: 'site' | 'room_type' | 'unit'
  scope_value: string | null
  scope_label: string
  amount: Money
  valid_from: string
  valid_to: string | null
  note: string | null
}

export interface GridCell {
  paid: string
  charged: string
  status: 'paid' | 'partial' | 'unpaid' | 'extra'
}

export interface GridData {
  periods: string[]
  blocks: { name: string; units: { unit_id: number; code: string; number: number; names: string[]; room_type: string | null; cells: Record<string, GridCell>; balance: string; overdue_months: number }[] }[]
  totals: Record<string, string>
}

export interface Debtor {
  unit_id: number
  code: string
  names: string[]
  charged: string
  paid: string
  balance: string
  overdue_months: number
  oldest_unpaid_period: string | null
  bucket: string
}

export interface Dashboard {
  site: { id: number; name: string }
  period: string
  charged_this_month: string
  collected_this_month: string
  collection_rate: number | null
  total_receivable: string
  total_advance: string
  debtor_units: number
  unit_count: number
  transactions: Record<string, number>
  needs_review: number
  last_transaction_date: string | null
  last_import: { file_name: string; at: string; kind: string } | null
  gaps: { after: string; before: string; message: string }[]
  monthly: { period: string; collected: string }[]
}

export interface StatementEntry {
  kind: 'charge' | 'payment'
  id: number
  transaction_id?: number
  period: string
  date: string
  type: string
  description: string
  debit: Money
  credit: Money
  balance: Money
  source: string
  method?: string
}

export interface BankImportResult {
  import_id: number
  site_id: number
  iban: string
  period_start: string | null
  period_end: string | null
  already_imported: boolean
  total_rows: number
  new: number
  duplicates: number
  before_cutoff: number
  auto_matched: number
  suggested: number
  unmatched: number
  outgoing_ignored: number
  credit_total: string
  footer_credit_total: string | null
  warnings: string[]
  gaps: { message: string }[]
}

export interface TrackingPreview {
  sheet: string
  start_year: number
  first_period: string
  last_period: string
  cutoff: string
  blocks: { name: string; unit_count: number }[]
  unit_count: number
  units: {
    block: string
    number: number
    code: string
    raw_name: string
    names: string[]
    payment_count: number
    legacy_total: string
    post_cutoff_total: string
    first_period: string | null
    one_offs: Record<string, string>
    tags: Record<string, unknown>
    expressions: Record<string, string>
  }[]
  legacy_total: string
  post_cutoff_total: string
  warnings: string[]
  notes: string[]
}

export interface OpeningRow {
  unit_id: number
  code: string
  start_period: string | null
  first_payment_period: string | null
  start_is_explicit: boolean
  months: number
  aidat_total: string
  other_charges: string
  payments: string
  computed_balance: string
  missing_tariff_periods: string[]
  missing_tariff_count: number
}

export interface PayerAlias {
  id: number
  display_name: string
  normalized_name: string
  mode: 'single' | 'split' | 'ambiguous'
  targets: { unit_id: number; ratio: number | null; code: string | null }[]
  source: string
  confirm_count: number
  auto_count: number
}
