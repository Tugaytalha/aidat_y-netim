import { Alert, Badge, Button, Card, Group, NumberInput, ScrollArea, Stack, Stepper, Table, Text, TextInput, Title } from '@mantine/core'
import { modals } from '@mantine/modals'
import { IconLock } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type OpeningRow, type Tariff } from '../api'
import { ErrorAlert, Loading, MoneyText, NoSite, notifyError, notifyOk, PageHeader } from '../components/common'
import { useAuth, useSite } from '../context'
import { addMonths, money, num, periodLabel } from '../format'

/** Dairenin aidat başlangıç ayı; boşsa site başlangıcı kullanılır. Odak kaybında kaydeder. */
function StartInput({ row, disabled, onSaved }: { row: OpeningRow; disabled: boolean; onSaved: () => void }) {
  const [value, setValue] = useState(row.start_period ?? '')
  useEffect(() => setValue(row.start_period ?? ''), [row.start_period])
  const save = useMutation({
    mutationFn: (v: string) => api.patch(`/api/units/${row.unit_id}`, { aidat_start_period: v || null }),
    onSuccess: onSaved,
    onError: notifyError,
  })
  return (
    <TextInput
      size="xs"
      w={96}
      value={value}
      placeholder="YYYY-AA"
      disabled={disabled}
      error={value && !/^\d{4}-(0[1-9]|1[0-2])$/.test(value) ? ' ' : undefined}
      styles={{ input: { fontWeight: row.start_is_explicit ? 600 : 400 } }}
      onChange={(e) => setValue(e.currentTarget.value)}
      onBlur={() => {
        if (value !== (row.start_period ?? '') && (!value || /^\d{4}-(0[1-9]|1[0-2])$/.test(value))) save.mutate(value)
      }}
    />
  )
}

interface Suggestion {
  periods: { valid_from: string; valid_to: string | null; amount: string; sample_size: number }[]
  unit_deviations: { unit_id: number; code: string; valid_from: string; valid_to: string | null; typical_amount: string; site_amount: string; samples: number }[]
}

export default function Opening() {
  const { siteId, site } = useSite()
  const { canWrite } = useAuth()
  const qc = useQueryClient()
  const [cutoff, setCutoff] = useState(site?.legacy_cutoff_period ?? '')
  useEffect(() => setCutoff(site?.legacy_cutoff_period ?? ''), [site?.legacy_cutoff_period])
  const [edits, setEdits] = useState<Record<number, { balance: number | string; note: string }>>({})

  const sug = useQuery({
    queryKey: ['tariff-suggest', siteId, cutoff],
    queryFn: () => api.get<Suggestion>(`/api/sites/${siteId}/opening/tariff-suggestions`, { cutoff }),
    enabled: !!siteId,
  })
  const tariffs = useQuery({ queryKey: ['tariffs', siteId], queryFn: () => api.get<Tariff[]>(`/api/sites/${siteId}/tariffs`), enabled: !!siteId })
  const comp = useQuery({
    queryKey: ['opening', siteId, cutoff],
    queryFn: () => api.get<{ cutoff: string; last_period: string; rows: OpeningRow[]; locked_until: string | null }>(`/api/sites/${siteId}/opening/compute`, { cutoff }),
    enabled: !!siteId && /^\d{4}-\d{2}$/.test(cutoff),
  })

  const applyTariffs = useMutation({
    mutationFn: async () => {
      for (const p of sug.data?.periods ?? []) {
        await api.post(`/api/sites/${siteId}/tariffs`, { amount: p.amount, valid_from: p.valid_from, valid_to: p.valid_to, note: 'Eski ödemelerden önerildi' })
      }
    },
    onSuccess: () => {
      notifyOk('Önerilen tarifeler eklendi. Gerekirse Tarife ve tahakkuk sayfasından düzeltin.')
      qc.invalidateQueries()
    },
    onError: notifyError,
  })
  const approve = useMutation({
    mutationFn: () =>
      api.post<{ locked_until: string; adjustments: number }>(`/api/sites/${siteId}/opening/approve`, {
        cutoff,
        rows: Object.entries(edits)
          .filter(([, v]) => v.balance !== '' && v.balance !== undefined)
          .map(([id, v]) => ({ unit_id: Number(id), approved_balance: String(v.balance), note: v.note || null })),
      }),
    onSuccess: (r) => {
      notifyOk(`Açılış bakiyeleri onaylandı; ${periodLabel(r.locked_until)} ve öncesi kilitlendi (${r.adjustments} düzeltme).`)
      setEdits({})
      qc.invalidateQueries()
    },
    onError: notifyError,
  })

  if (!siteId) return <NoSite />
  const rows = comp.data?.rows ?? []
  const missing = rows.reduce((s, r) => s + r.missing_tariff_count, 0)
  const locked = comp.data?.locked_until
  const totalComputed = rows.reduce((s, r) => s + num(r.computed_balance), 0)
  const totalApproved = rows.reduce((s, r) => s + num(edits[r.unit_id]?.balance !== undefined && edits[r.unit_id]?.balance !== '' ? edits[r.unit_id].balance : r.computed_balance), 0)
  const step = !tariffs.data?.length ? 0 : locked ? 2 : 1

  return (
    <>
      <PageHeader
        title="Açılış bakiyesi"
        description="Takip Excel'indeki geçmiş ödemeler ve dönemsel aidat tarifesinden, kesim ayına kadar her dairenin borcu hesaplanır. Düzenleyip onayladığınızda geçmiş dönemler kilitlenir."
        actions={<TextInput label="Kesim ayı" value={cutoff} onChange={(e) => setCutoff(e.currentTarget.value)} w={120} placeholder="2026-01" />}
      />
      <Stepper active={step} mb="lg" size="sm">
        <Stepper.Step label="Tarife geçmişi" description="Dönem tutarları" />
        <Stepper.Step label="Bakiyeleri gözden geçir" description="Düzenle" />
        <Stepper.Step label="Onaylandı" description="Kilitli" />
      </Stepper>

      <Card withBorder padding="lg" mb="lg">
        <Title order={4} mb="xs">
          1. Tarife geçmişi önerisi
        </Title>
        <Text size="sm" c="dimmed" mb="xs">
          Not: Daire başlangıcı varsayılan olarak sitenin başlangıç ayıdır (ilk ödeme ayı değil); böylece hiç ya da geç ödeyenlerin eski borcu
          kaybolmaz. Daire sonradan teslim edildiyse aşağıdaki tablodan başlangıç ayını değiştirin.
        </Text>
        <Text size="sm" c="dimmed" mb="sm">
          Her ay dairelerin en sık ödediği tutar. Ödeme tutarları her zaman aidata eşit olmadığından kontrol edin.
        </Text>
        {sug.isLoading ? (
          <Loading />
        ) : sug.data && sug.data.periods.length > 0 ? (
          <>
            <Table fz="sm" maw={560} striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Başlangıç</Table.Th>
                  <Table.Th>Bitiş</Table.Th>
                  <Table.Th className="num">Tutar</Table.Th>
                  <Table.Th className="num">Örnek</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {sug.data.periods.map((p) => (
                  <Table.Tr key={p.valid_from}>
                    <Table.Td>{periodLabel(p.valid_from)}</Table.Td>
                    <Table.Td>{p.valid_to ? periodLabel(p.valid_to) : 'devam'}</Table.Td>
                    <Table.Td className="num"><MoneyText value={p.amount} /></Table.Td>
                    <Table.Td className="num">{p.sample_size}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {sug.data.unit_deviations.length > 0 && (
              <Alert color="blue" mt="sm" title="Site tutarından sistematik farklı ödeyen daireler (oda tipi farkı olabilir)">
                <Text size="sm">
                  {sug.data.unit_deviations.slice(0, 20).map((d) => `${d.code}: ${money(d.typical_amount)} (${periodLabel(d.valid_from, true)}–${d.valid_to ? periodLabel(d.valid_to, true) : '…'})`).join(' · ')}
                </Text>
                <Text size="xs" c="dimmed" mt={4}>
                  Bu dairelere Daireler sayfasından oda tipi atayıp Tarife sayfasında oda tipine özel tutar tanımlayabilirsiniz.
                </Text>
              </Alert>
            )}
            {canWrite && (tariffs.data?.length ?? 0) === 0 && (
              <Button mt="sm" loading={applyTariffs.isPending} onClick={() => applyTariffs.mutate()}>
                Bu tutarları site tarifesi olarak ekle
              </Button>
            )}
            {(tariffs.data?.length ?? 0) > 0 && (
              <Text size="sm" mt="sm">
                Sitede {tariffs.data!.length} tarife tanımlı. <Link to="/tahakkuk">Tarifeleri düzenle</Link>
              </Text>
            )}
          </>
        ) : (
          <Text size="sm" c="dimmed">
            Eski ödeme verisi yok. Yeni sitelerde açılış bakiyesini aşağıda elle girin (devir).
          </Text>
        )}
      </Card>

      <Card withBorder padding="lg">
        <Group justify="space-between" mb="sm">
          <Title order={4}>2. Kesim öncesi bakiyeler ({comp.data ? periodLabel(comp.data.last_period) : '—'} sonu)</Title>
          {locked && (
            <Badge leftSection={<IconLock size={12} />} color="gray" size="lg">
              {periodLabel(locked)} ve öncesi kilitli
            </Badge>
          )}
        </Group>
        <ErrorAlert error={comp.error} />
        {missing > 0 && (
          <Alert color="yellow" mb="sm">
            {missing} daire-ay için tarife bulunamadı; bu aylara borç yazılmadı. Önce tarife geçmişini tamamlayın.
          </Alert>
        )}
        {comp.isLoading ? (
          <Loading />
        ) : (
          <ScrollArea h={480}>
            <Table fz="sm" striped stickyHeader>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Daire</Table.Th>
                  <Table.Th>Aidat başlangıcı</Table.Th>
                  <Table.Th>İlk ödeme</Table.Th>
                  <Table.Th className="num">Aidat (ay)</Table.Th>
                  <Table.Th className="num">Ödenen</Table.Th>
                  <Table.Th className="num">Hesaplanan</Table.Th>
                  <Table.Th>Onaylanan bakiye</Table.Th>
                  <Table.Th>Gerekçe</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((r) => {
                  const e = edits[r.unit_id]
                  return (
                    <Table.Tr key={r.unit_id}>
                      <Table.Td fw={600}>{r.code}</Table.Td>
                      <Table.Td>
                        <StartInput row={r} disabled={!canWrite || !!locked} onSaved={() => qc.invalidateQueries({ queryKey: ['opening', siteId] })} />
                      </Table.Td>
                      <Table.Td>{periodLabel(r.first_payment_period, true)}</Table.Td>
                      <Table.Td className="num">
                        <MoneyText value={r.aidat_total} /> <Text span size="xs" c="dimmed">({r.months})</Text>
                      </Table.Td>
                      <Table.Td className="num"><MoneyText value={r.payments} /></Table.Td>
                      <Table.Td className="num"><MoneyText value={r.computed_balance} colored fw={600} /></Table.Td>
                      <Table.Td>
                        <NumberInput size="xs" w={130} placeholder={String(num(r.computed_balance))} value={e?.balance ?? ''} disabled={!canWrite}
                          onChange={(v) => setEdits({ ...edits, [r.unit_id]: { balance: v, note: e?.note ?? '' } })} decimalScale={2} />
                      </Table.Td>
                      <Table.Td>
                        <TextInput size="xs" placeholder="ör. eski borç mutabakatı" value={e?.note ?? ''} disabled={!canWrite || !e || e.balance === ''}
                          onChange={(ev) => setEdits({ ...edits, [r.unit_id]: { balance: e?.balance ?? '', note: ev.currentTarget.value } })} />
                      </Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
        <Group justify="space-between" mt="md">
          <Text size="sm">
            Hesaplanan toplam <MoneyText value={totalComputed} fw={600} /> · onaylanacak toplam <MoneyText value={totalApproved} fw={600} />
          </Text>
          {canWrite && (
            <Button
              leftSection={<IconLock size={16} />}
              loading={approve.isPending}
              disabled={!rows.length}
              onClick={() =>
                modals.openConfirmModal({
                  title: 'Açılış bakiyelerini onayla',
                  children: (
                    <Stack gap="xs">
                      <Text size="sm">
                        {periodLabel(addMonths(cutoff, -1))} ve öncesi için aidat tahakkukları yazılacak, değiştirdiğiniz bakiyeler "düzeltme" kaydı olarak eklenecek ve bu dönem kilitlenecek.
                      </Text>
                      {locked && <Text size="sm" c="orange">Daha önce onaylanmış; yeniden onay önceki açılış kayıtlarını değiştirir (yönetici yetkisi gerekir).</Text>}
                    </Stack>
                  ),
                  onConfirm: () => approve.mutate(),
                })
              }
            >
              Onayla ve kilitle
            </Button>
          )}
        </Group>
      </Card>
    </>
  )
}
