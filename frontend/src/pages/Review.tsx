import {
  ActionIcon, Alert, Badge, Button, Card, Checkbox, Group, Modal, NumberInput, Pagination, Paper, SegmentedControl, Select,
  Stack, Text, TextInput, Tooltip,
} from '@mantine/core'
import { IconCheck, IconEyeOff, IconPlus, IconRobot, IconArrowsSplit, IconTrash, IconRefresh } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Page, type Txn } from '../api'
import { Loading, MoneyText, NoSite, notifyError, notifyOk, PageHeader, StatusBadge, UnitSelect, useUnits } from '../components/common'
import { CandidateSignals, HighlightedDescription } from '../components/TxnParts'
import { useAuth, useSite } from '../context'
import { CATEGORY_LABELS, dateTR, money, num, periodLabel } from '../format'

const CATEGORY_OPTIONS = ['aidat', 'demirbas', 'asansor', 'ek_butce', 'diger'].map((v) => ({ value: v, label: CATEGORY_LABELS[v] }))

export default function Review() {
  const { siteId, site } = useSite()
  const { canWrite } = useAuth()
  const qc = useQueryClient()
  const [status, setStatus] = useState('suggested,unmatched')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number[]>([])
  const q = useQuery({
    queryKey: ['transactions', siteId, 'review', status, page],
    queryFn: () => api.get<Page<Txn>>(`/api/sites/${siteId}/transactions`, { status, page, page_size: 25 }),
    enabled: !!siteId,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['transactions'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
    qc.invalidateQueries({ queryKey: ['units'] })
  }
  const bulk = useMutation({
    mutationFn: () => api.post<{ confirmed: number; skipped: number[] }>(`/api/sites/${siteId}/transactions/bulk-confirm`, { transaction_ids: selected }),
    onSuccess: (r) => {
      notifyOk(`${r.confirmed} işlem onaylandı${r.skipped.length ? `, ${r.skipped.length} atlandı` : ''}`)
      setSelected([])
      refresh()
    },
    onError: notifyError,
  })
  const rematch = useMutation({
    mutationFn: () => api.post<{ processed: number; auto: number }>(`/api/sites/${siteId}/transactions/rematch`),
    onSuccess: (r) => {
      notifyOk(`${r.processed} bekleyen işlem yeniden değerlendirildi, ${r.auto} tanesi otomatik eşleşti`)
      refresh()
    },
    onError: notifyError,
  })

  if (!siteId) return <NoSite />
  const items = q.data?.items ?? []
  const pages = Math.max(1, Math.ceil((q.data?.total ?? 0) / 25))

  return (
    <>
      <PageHeader
        title="İnceleme kuyruğu"
        description="Motorun emin olamadığı ödemeler. Onayladığınız gönderen bir sonraki ekstrede otomatik eşleşir ('hatırla'). Ödeme, gönderildiği aya yazılır."
        actions={
          canWrite && (
            <>
              <Tooltip label="Hafıza ve tarifeler değiştiyse bekleyenleri yeniden değerlendirir">
                <Button variant="default" leftSection={<IconRefresh size={16} />} loading={rematch.isPending} onClick={() => rematch.mutate()}>
                  Yeniden eşleştir
                </Button>
              </Tooltip>
              <Button leftSection={<IconCheck size={16} />} disabled={!selected.length} loading={bulk.isPending} onClick={() => bulk.mutate()}>
                Seçilenleri onayla ({selected.length})
              </Button>
            </>
          )
        }
      />
      <SegmentedControl
        mb="md"
        value={status}
        onChange={(v) => {
          setStatus(v)
          setPage(1)
          setSelected([])
        }}
        data={[
          { value: 'suggested,unmatched', label: 'Bekleyenler' },
          { value: 'suggested', label: 'Öneriler' },
          { value: 'unmatched', label: 'Eşleşmeyenler' },
          { value: 'ignored', label: 'Yok sayılanlar' },
        ]}
      />
      {q.isLoading && <Loading />}
      {!q.isLoading && items.length === 0 && (
        <Alert color="teal" title="Kuyruk boş">
          İncelenecek işlem yok.
        </Alert>
      )}
      <Stack>
        {items.map((t) => (
          <ReviewCard
            key={t.id}
            txn={t}
            llmEnabled={!!site?.llm_enabled}
            canWrite={canWrite}
            checked={selected.includes(t.id)}
            onCheck={(c) => setSelected(c ? [...selected, t.id] : selected.filter((x) => x !== t.id))}
            onDone={refresh}
          />
        ))}
      </Stack>
      {pages > 1 && <Pagination mt="md" total={pages} value={page} onChange={setPage} />}
    </>
  )
}

interface Row {
  unit: string | null
  amount: number | string
  category: string
}

function ReviewCard({ txn, llmEnabled, canWrite, checked, onCheck, onDone }: {
  txn: Txn; llmEnabled: boolean; canWrite: boolean; checked: boolean; onCheck: (c: boolean) => void; onDone: () => void
}) {
  const units = useUnits()
  const codeOf = (id: number) => units.data?.find((u) => u.id === id)?.code ?? String(id)
  const [remember, setRemember] = useState(true)
  const [category, setCategory] = useState<string>(txn.category_hint ?? 'aidat')
  const [pick, setPick] = useState<string | null>(null)
  const [splitOpen, setSplitOpen] = useState(false)
  const [ignoreOpen, setIgnoreOpen] = useState(false)
  const [note, setNote] = useState('')
  const [current, setCurrent] = useState(txn)

  const confirm = useMutation({
    mutationFn: (allocations: { unit_id: number; amount: string; category: string }[]) =>
      api.post<Txn>(`/api/transactions/${txn.id}/confirm`, { allocations, remember }),
    onSuccess: (t) => {
      notifyOk(`${t.allocations.map((a) => a.code).join(' + ')} olarak kaydedildi`)
      onDone()
    },
    onError: notifyError,
  })
  const ignore = useMutation({
    mutationFn: () => api.post<Txn>(`/api/transactions/${txn.id}/ignore`, { note: note || 'Aidat dışı' }),
    onSuccess: () => {
      setIgnoreOpen(false)
      onDone()
    },
    onError: notifyError,
  })
  const llm = useMutation({
    mutationFn: () => api.post<Txn>(`/api/transactions/${txn.id}/llm-suggest`),
    onSuccess: setCurrent,
    onError: notifyError,
  })

  const single = (unitId: number) => confirm.mutate([{ unit_id: unitId, amount: String(txn.amount), category }])
  const t = current
  const ai = t.llm

  return (
    <Card withBorder padding="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Group align="flex-start" wrap="nowrap" gap="sm">
          {canWrite && t.status === 'suggested' && <Checkbox checked={checked} onChange={(e) => onCheck(e.currentTarget.checked)} mt={4} aria-label="Seç" />}
          <Stack gap={4}>
            <Group gap="xs">
              <Text fw={700} size="lg">
                <MoneyText value={t.amount} />
              </Text>
              <Text c="dimmed" size="sm">
                {dateTR(t.txn_date)} · {t.payer_name ?? 'gönderen bilinmiyor'}
              </Text>
              <StatusBadge status={t.status} />
              {t.conflict && <Badge color="orange">Çelişki</Badge>}
            </Group>
            <HighlightedDescription txn={t} />
            <Group gap="xs">
              {t.stated_periods.length > 0 && (
                <Text size="xs" c="dimmed">
                  Açıklamadaki ay: {t.stated_periods.map((p) => periodLabel(p)).join(', ')}
                </Text>
              )}
              {t.period_note && <Badge size="xs" variant="outline">{t.period_note}</Badge>}
              {t.reasons.map((r) => (
                <Text key={r} size="xs" c={r.startsWith('Çelişki') ? 'orange' : 'dimmed'}>
                  • {r}
                </Text>
              ))}
            </Group>
          </Stack>
        </Group>
      </Group>

      {t.split && (
        <Paper withBorder p="xs" mt="sm" bg="var(--mantine-color-default-hover)">
          <Group justify="space-between">
            <Group gap="xs">
              <IconArrowsSplit size={16} />
              <Text size="sm">Bölüştürme önerisi: {t.split.map((s) => `${codeOf(s.unit_id)} ${money(s.amount)}`).join(' + ')}</Text>
            </Group>
            {canWrite && (
              <Button size="xs" loading={confirm.isPending}
                onClick={() => confirm.mutate(t.split!.map((s) => ({ unit_id: s.unit_id, amount: s.amount, category })))}>
                Bölüştürerek onayla
              </Button>
            )}
          </Group>
        </Paper>
      )}

      {t.candidates.length > 0 && (
        <Stack gap={6} mt="sm">
          {t.candidates.slice(0, 4).map((c) => (
            <Group key={c.unit_id} justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap">
                <Badge variant="outline" size="lg" miw={64}>
                  {c.code}
                </Badge>
                <Text size="sm" fw={600} w={42}>
                  %{Math.round(c.score * 100)}
                </Text>
                <Text size="xs" c="dimmed" visibleFrom="sm" lineClamp={1}>
                  {units.data?.find((u) => u.id === c.unit_id)?.people.map((p) => p.name).join(' / ')}
                </Text>
                <CandidateSignals c={c} />
              </Group>
              {canWrite && (
                <Button size="xs" variant="light" loading={confirm.isPending} onClick={() => single(c.unit_id)}>
                  Bu daireye ata
                </Button>
              )}
            </Group>
          ))}
        </Stack>
      )}

      {ai && (
        <Alert mt="sm" color="violet" icon={<IconRobot size={18} />} title={`AI önerisi (%${Math.round(ai.confidence * 100)})`}>
          <Text size="sm">{ai.reason}</Text>
          <Group mt={6} gap="xs">
            {ai.split
              ? canWrite && (
                  <Button size="xs" color="violet" variant="light"
                    onClick={() => confirm.mutate(ai.split!.map((s) => ({ unit_id: s.unit_id, amount: s.amount, category: ai.category ?? category })))}>
                    {ai.split.map((s) => `${codeOf(s.unit_id)} ${money(s.amount)}`).join(' + ')} olarak onayla
                  </Button>
                )
              : ai.unit_ids.map((u) =>
                  canWrite ? (
                    <Button key={u} size="xs" color="violet" variant="light" onClick={() => single(u)}>
                      {codeOf(u)} olarak onayla
                    </Button>
                  ) : (
                    <Badge key={u}>{codeOf(u)}</Badge>
                  ),
                )}
          </Group>
        </Alert>
      )}

      {canWrite && (
        <Group mt="sm" gap="xs" wrap="wrap">
          <UnitSelect value={pick} onChange={setPick} w={260} size="xs" />
          <Button size="xs" disabled={!pick} loading={confirm.isPending} onClick={() => pick && single(Number(pick))}>
            Ata
          </Button>
          <Select size="xs" w={120} data={CATEGORY_OPTIONS} value={category} onChange={(v) => setCategory(v ?? 'aidat')} allowDeselect={false} />
          <Button size="xs" variant="default" leftSection={<IconArrowsSplit size={14} />} onClick={() => setSplitOpen(true)}>
            Böl
          </Button>
          <Button size="xs" variant="default" leftSection={<IconEyeOff size={14} />} onClick={() => setIgnoreOpen(true)}>
            Yok say
          </Button>
          {llmEnabled && (
            <Button size="xs" variant="subtle" color="violet" leftSection={<IconRobot size={14} />} loading={llm.isPending} onClick={() => llm.mutate()}>
              AI ile öner
            </Button>
          )}
          <Checkbox size="xs" label="Bu göndereni hatırla" checked={remember} onChange={(e) => setRemember(e.currentTarget.checked)} />
        </Group>
      )}

      <SplitModal
        opened={splitOpen}
        onClose={() => setSplitOpen(false)}
        txn={t}
        category={category}
        loading={confirm.isPending}
        onSubmit={(rows) => confirm.mutate(rows.map((r) => ({ unit_id: Number(r.unit), amount: String(r.amount), category: r.category })))}
      />
      <Modal opened={ignoreOpen} onClose={() => setIgnoreOpen(false)} title="İşlemi yok say">
        <Stack>
          <Text size="sm">Bu ödeme hiçbir daireye yazılmayacak (iade, faiz, yanlış gönderim vb.).</Text>
          <TextInput label="Not" placeholder="ör. yanlış hesaba gönderilmiş, iade edilecek" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
          <Button color="gray" loading={ignore.isPending} onClick={() => ignore.mutate()}>
            Yok say
          </Button>
        </Stack>
      </Modal>
    </Card>
  )
}

function SplitModal({ opened, onClose, txn, category, loading, onSubmit }: {
  opened: boolean; onClose: () => void; txn: Txn; category: string; loading: boolean; onSubmit: (rows: Row[]) => void
}) {
  const initial: Row[] = txn.split
    ? txn.split.map((s) => ({ unit: String(s.unit_id), amount: Number(s.amount), category }))
    : [
        { unit: txn.candidates[0] ? String(txn.candidates[0].unit_id) : null, amount: num(txn.amount) / 2, category },
        { unit: txn.candidates[1] ? String(txn.candidates[1].unit_id) : null, amount: num(txn.amount) / 2, category },
      ]
  const [rows, setRows] = useState<Row[]>(initial)
  const total = rows.reduce((s, r) => s + num(r.amount as number), 0)
  const diff = Math.round((num(txn.amount) - total) * 100) / 100
  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (i === j ? { ...r, ...patch } : r)))
  return (
    <Modal opened={opened} onClose={onClose} title={`Ödemeyi böl — ${money(txn.amount)}`} size="lg">
      <Stack>
        {rows.map((r, i) => (
          <Group key={i} wrap="nowrap" align="flex-end">
            <UnitSelect label={i === 0 ? 'Daire' : undefined} value={r.unit} onChange={(v) => set(i, { unit: v })} style={{ flex: 1 }} />
            <NumberInput label={i === 0 ? 'Tutar' : undefined} value={r.amount} onChange={(v) => set(i, { amount: v })} w={130} min={0} decimalScale={2} />
            <Select label={i === 0 ? 'Kategori' : undefined} data={CATEGORY_OPTIONS} value={r.category} onChange={(v) => set(i, { category: v ?? 'aidat' })} w={120} />
            <ActionIcon variant="subtle" color="red" onClick={() => setRows(rows.filter((_, j) => j !== i))} disabled={rows.length < 2} aria-label="Satırı sil">
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        ))}
        <Group justify="space-between">
          <Button variant="subtle" size="xs" leftSection={<IconPlus size={14} />} onClick={() => setRows([...rows, { unit: null, amount: diff > 0 ? diff : 0, category }])}>
            Satır ekle
          </Button>
          <Text size="sm" c={diff === 0 ? 'teal' : diff > 0 ? 'yellow.8' : 'red'}>
            {diff === 0 ? 'Toplam tutuyor' : diff > 0 ? `${money(diff)} dağıtılmadı (alacak olarak kalmaz, işlemde açık kalır)` : `${money(-diff)} fazla`}
          </Text>
        </Group>
        <Button loading={loading} disabled={diff < 0 || rows.some((r) => !r.unit || !num(r.amount as number))} onClick={() => onSubmit(rows)}>
          Kaydet
        </Button>
      </Stack>
    </Modal>
  )
}
