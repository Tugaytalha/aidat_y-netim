import { ActionIcon, Alert, Button, Card, Group, MultiSelect, NumberInput, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { modals } from '@mantine/modals'
import { IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Tariff } from '../api'
import { ErrorAlert, MoneyText, NoSite, notifyError, notifyOk, PageHeader, useUnits } from '../components/common'
import { useAuth, useSite } from '../context'
import { addMonths, CATEGORY_LABELS, currentPeriod, periodLabel, periodOptions } from '../format'

export default function Ledger() {
  const { siteId } = useSite()
  const { canWrite } = useAuth()
  if (!siteId) return <NoSite />
  return (
    <>
      <PageHeader
        title="Tarife ve tahakkuk"
        description="Aylık aidat tarifeleri (tüm site, oda tipi ya da daire bazında; geçerlilik tarihli) ve tahakkuk üretimi. Öncelik: daire > oda tipi > site."
      />
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Tariffs siteId={siteId} canWrite={canWrite} />
        <Stack>
          {canWrite && <Generate siteId={siteId} />}
          {canWrite && <Batch siteId={siteId} />}
        </Stack>
      </SimpleGrid>
    </>
  )
}

function Tariffs({ siteId, canWrite }: { siteId: number; canWrite: boolean }) {
  const qc = useQueryClient()
  const units = useUnits()
  const q = useQuery({ queryKey: ['tariffs', siteId], queryFn: () => api.get<Tariff[]>(`/api/sites/${siteId}/tariffs`) })
  const [scope, setScope] = useState('site')
  const [value, setValue] = useState<string | null>(null)
  const [amount, setAmount] = useState<number | string>('')
  const [from, setFrom] = useState(currentPeriod())
  const [pct, setPct] = useState<number | string>('')
  const [incFrom, setIncFrom] = useState(addMonths(currentPeriod(), 1))
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['tariffs', siteId] })
  }
  const add = useMutation({
    mutationFn: () => api.post(`/api/sites/${siteId}/tariffs`, { scope, scope_value: scope === 'site' ? null : value, amount: String(amount), valid_from: from }),
    onSuccess: () => {
      notifyOk('Tarife eklendi; aynı kapsamdaki önceki tarife bir ay önce kapatıldı')
      setAmount('')
      refresh()
    },
    onError: notifyError,
  })
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/tariffs/${id}`), onSuccess: refresh, onError: notifyError })
  const inc = useMutation({
    mutationFn: () => api.post<Tariff[]>(`/api/sites/${siteId}/tariffs/increase`, { valid_from: incFrom, percent: String(pct) }),
    onSuccess: (r) => {
      notifyOk(`${r.length} tarife ${periodLabel(incFrom)} itibarıyla artırıldı`)
      refresh()
    },
    onError: notifyError,
  })
  const roomTypes = Array.from(new Set((units.data ?? []).map((u) => u.room_type).filter(Boolean))) as string[]
  const opts = periodOptions(addMonths(currentPeriod(), -48), addMonths(currentPeriod(), 12))

  return (
    <Card withBorder padding="lg">
      <Title order={4} mb="sm">
        Tarifeler
      </Title>
      <ErrorAlert error={q.error} />
      <Table fz="sm" striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Kapsam</Table.Th>
            <Table.Th className="num">Tutar</Table.Th>
            <Table.Th>Geçerlilik</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {q.data?.map((t) => (
            <Table.Tr key={t.id}>
              <Table.Td>{t.scope_label}</Table.Td>
              <Table.Td className="num">
                <MoneyText value={t.amount} />
              </Table.Td>
              <Table.Td>
                {periodLabel(t.valid_from)} → {t.valid_to ? periodLabel(t.valid_to) : 'devam ediyor'}
              </Table.Td>
              <Table.Td>
                {canWrite && (
                  <ActionIcon variant="subtle" color="red" aria-label="Sil"
                    onClick={() => modals.openConfirmModal({ title: 'Tarife silinsin mi?', children: <Text size="sm">Mevcut tahakkuklar değişmez.</Text>, onConfirm: () => del.mutate(t.id) })}>
                    <IconTrash size={16} />
                  </ActionIcon>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {q.data?.length === 0 && <Alert mt="sm" color="yellow">Tarife yok: tahakkuk üretilemez.</Alert>}
      {canWrite && (
        <Stack mt="md" gap="xs">
          <Text fw={600} size="sm">
            Yeni tarife
          </Text>
          <SegmentedControl
            size="xs"
            value={scope}
            onChange={(v) => { setScope(v); setValue(null) }}
            data={[
              { value: 'site', label: 'Tüm site' },
              { value: 'room_type', label: 'Oda tipi' },
              { value: 'unit', label: 'Daire' },
            ]}
          />
          <Group grow align="flex-end">
            {scope === 'room_type' && (
              <Select label="Oda tipi" data={roomTypes} value={value} onChange={setValue} placeholder={roomTypes.length ? 'Seçin' : 'Önce dairelere oda tipi atayın'} />
            )}
            {scope === 'unit' && (
              <Select label="Daire" searchable data={(units.data ?? []).map((u) => ({ value: String(u.id), label: u.code }))} value={value} onChange={setValue} />
            )}
            <NumberInput label="Aylık tutar" value={amount} onChange={setAmount} min={0} thousandSeparator="." decimalSeparator="," />
            <Select label="Başlangıç" data={opts} value={from} onChange={(v) => v && setFrom(v)} allowDeselect={false} searchable />
          </Group>
          <Button onClick={() => add.mutate()} loading={add.isPending} disabled={!amount || (scope !== 'site' && !value)} w="fit-content">
            Ekle
          </Button>
          <Text fw={600} size="sm" mt="md">
            Toplu artış
          </Text>
          <Group align="flex-end">
            <NumberInput label="Yüzde" value={pct} onChange={setPct} suffix=" %" w={110} />
            <Select label="Geçerli olacağı ay" data={opts} value={incFrom} onChange={(v) => v && setIncFrom(v)} w={170} allowDeselect={false} />
            <Button variant="default" disabled={!pct} loading={inc.isPending}
              onClick={() => modals.openConfirmModal({ title: 'Toplu artış', children: <Text size="sm">{periodLabel(incFrom)} itibarıyla geçerli tüm tarifeler %{pct} artırılacak (50 TL'ye yuvarlanır).</Text>, onConfirm: () => inc.mutate() })}>
              Uygula
            </Button>
          </Group>
        </Stack>
      )}
    </Card>
  )
}

function Generate({ siteId }: { siteId: number }) {
  const qc = useQueryClient()
  const [start, setStart] = useState(currentPeriod())
  const [end, setEnd] = useState(currentPeriod())
  const gen = useMutation({
    mutationFn: () => api.post<{ period: string; created: number; skipped_no_tariff: number; already_exists: number }[]>(`/api/sites/${siteId}/charges/generate`, { start, end }),
    onSuccess: (r) => {
      const created = r.reduce((s, x) => s + x.created, 0)
      const noTariff = r.reduce((s, x) => s + x.skipped_no_tariff, 0)
      notifyOk(`${created} tahakkuk oluşturuldu${noTariff ? `, ${noTariff} daire tarifesiz atlandı` : ''}`)
      qc.invalidateQueries()
    },
    onError: notifyError,
  })
  const opts = periodOptions(addMonths(currentPeriod(), -36), addMonths(currentPeriod(), 3))
  return (
    <Card withBorder padding="lg">
      <Title order={4} mb="xs">
        Aylık aidat tahakkuku
      </Title>
      <Text size="sm" c="dimmed" mb="sm">
        Seçilen aylar için her daireye tarifesine göre aidat borcu yazar. Tekrar çalıştırmak güvenlidir: aynı ay ikinci kez yazılmaz.
      </Text>
      <Group align="flex-end">
        <Select label="Başlangıç" data={opts} value={start} onChange={(v) => v && setStart(v)} w={160} allowDeselect={false} />
        <Select label="Bitiş" data={opts} value={end} onChange={(v) => v && setEnd(v)} w={160} allowDeselect={false} />
        <Button loading={gen.isPending} onClick={() => gen.mutate()}>
          Tahakkuk oluştur
        </Button>
      </Group>
    </Card>
  )
}

function Batch({ siteId }: { siteId: number }) {
  const qc = useQueryClient()
  const units = useUnits()
  const [type, setType] = useState('demirbas')
  const [period, setPeriod] = useState(currentPeriod())
  const [amount, setAmount] = useState<number | string>('')
  const [desc, setDesc] = useState('')
  const [only, setOnly] = useState<string[]>([])
  const save = useMutation({
    mutationFn: () =>
      api.post(`/api/sites/${siteId}/charge-batches`, { type, period, amount: String(amount), description: desc, unit_ids: only.length ? only.map(Number) : null }),
    onSuccess: () => {
      notifyOk('Toplu tahakkuk oluşturuldu')
      setAmount('')
      setDesc('')
      qc.invalidateQueries()
    },
    onError: notifyError,
  })
  return (
    <Card withBorder padding="lg">
      <Title order={4} mb="xs">
        Tek seferlik toplu tahakkuk
      </Title>
      <Text size="sm" c="dimmed" mb="sm">
        Demirbaş, asansör tadilatı, ek bütçe gibi kalemler. Tutar eşleştirmede ipucu olarak da kullanılır (ör. 2.000 TL gelen ödeme → demirbaş).
      </Text>
      <Stack gap="xs">
        <Group grow>
          <Select label="Tür" value={type} onChange={(v) => setType(v ?? 'demirbas')} allowDeselect={false}
            data={['demirbas', 'asansor', 'ek_butce'].map((v) => ({ value: v, label: CATEGORY_LABELS[v] }))} />
          <Select label="Dönem" data={periodOptions(addMonths(currentPeriod(), -24), addMonths(currentPeriod(), 3))} value={period} onChange={(v) => v && setPeriod(v)} allowDeselect={false} />
          <NumberInput label="Daire başı tutar" value={amount} onChange={setAmount} min={0} />
        </Group>
        <TextInput label="Açıklama" placeholder="ör. Şifrematik kapı sistemi" value={desc} onChange={(e) => setDesc(e.currentTarget.value)} />
        <MultiSelect label="Sadece bu daireler (boş = tümü)" searchable data={(units.data ?? []).map((u) => ({ value: String(u.id), label: u.code }))} value={only} onChange={setOnly} />
        <Button loading={save.isPending} disabled={!amount || desc.length < 3} onClick={() => save.mutate()} w="fit-content">
          Oluştur
        </Button>
      </Stack>
    </Card>
  )
}
