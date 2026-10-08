import { ActionIcon, Badge, Button, Group, Menu, Modal, NumberInput, Pagination, Select, Stack, Table, Text, TextInput } from '@mantine/core'
import { IconDots, IconPlus, IconSearch } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Page, type Txn } from '../api'
import { ErrorAlert, Loading, MoneyText, NoSite, notifyError, notifyOk, PageHeader, StatusBadge, UnitSelect } from '../components/common'
import { useAuth, useSite } from '../context'
import { CATEGORY_LABELS, dateTR, METHOD_LABELS } from '../format'

export default function Transactions() {
  const { siteId } = useSite()
  const { canWrite } = useAuth()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [source, setSource] = useState<string>('bank')
  const [page, setPage] = useState(1)
  const [manual, setManual] = useState(false)
  const query = useQuery({
    queryKey: ['transactions', siteId, 'list', q, status, source, page],
    queryFn: () => api.get<Page<Txn>>(`/api/sites/${siteId}/transactions`, { q, status, source, page, page_size: 50 }),
    enabled: !!siteId,
  })
  const reset = useMutation({
    mutationFn: (id: number) => api.post<Txn>(`/api/transactions/${id}/reset`),
    onSuccess: (t) => {
      notifyOk(`Yeniden değerlendirildi: ${t.status === 'matched' ? 'eşleşti' : 'incelemeye düştü'}`)
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['units'] })
    },
    onError: notifyError,
  })
  if (!siteId) return <NoSite />
  const data = query.data
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / 50))

  return (
    <>
      <PageHeader
        title="İşlemler"
        description="Banka ekstrelerinden gelen tüm hareketler, elden ödemeler ve eski Excel'den aktarılan ödemeler."
        actions={
          canWrite && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setManual(true)}>
              Elden ödeme
            </Button>
          )
        }
      />
      <Group mb="md" gap="sm">
        <TextInput leftSection={<IconSearch size={16} />} placeholder="Açıklama ya da gönderen" value={q} onChange={(e) => { setQ(e.currentTarget.value); setPage(1) }} w={260} />
        <Select
          placeholder="Durum"
          clearable
          w={160}
          value={status}
          onChange={(v) => { setStatus(v); setPage(1) }}
          data={[
            { value: 'matched', label: 'Eşleşti' },
            { value: 'suggested', label: 'Öneri' },
            { value: 'unmatched', label: 'Eşleşmedi' },
            { value: 'ignored', label: 'Yok sayıldı' },
          ]}
        />
        <Select
          w={170}
          value={source}
          onChange={(v) => { setSource(v ?? 'bank'); setPage(1) }}
          allowDeselect={false}
          data={[
            { value: 'bank', label: 'Banka' },
            { value: 'manual', label: 'Elden' },
            { value: 'legacy_excel', label: 'Eski Excel' },
          ]}
        />
        <Text size="sm" c="dimmed">
          {data?.total ?? 0} kayıt
        </Text>
      </Group>
      <ErrorAlert error={query.error} />
      {query.isLoading ? (
        <Loading />
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table striped fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Tarih</Table.Th>
                <Table.Th>Açıklama</Table.Th>
                <Table.Th className="num">Tutar</Table.Th>
                <Table.Th>Durum</Table.Th>
                <Table.Th>Daire</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data?.items.map((t) => (
                <Table.Tr key={t.id}>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>{dateTR(t.txn_date)}</Table.Td>
                  <Table.Td>
                    <Text size="sm" lineClamp={2}>
                      {t.description}
                    </Text>
                    {t.note && (
                      <Text size="xs" c="dimmed">
                        Not: {t.note}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td className="num">
                    <MoneyText value={t.amount} />
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge status={t.status} />
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {t.allocations.map((a) => (
                        <Badge key={a.id} variant="light" title={`${METHOD_LABELS[a.method] ?? a.method} · ${CATEGORY_LABELS[a.category] ?? a.category}`}>
                          {a.code}
                          {t.allocations.length > 1 ? ` ${Number(a.amount).toLocaleString('tr-TR')}` : ''}
                        </Badge>
                      ))}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {canWrite && t.source === 'bank' && (
                      <Menu position="bottom-end">
                        <Menu.Target>
                          <ActionIcon variant="subtle" aria-label="İşlemler">
                            <IconDots size={16} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown>
                          <Menu.Item onClick={() => reset.mutate(t.id)}>Eşleşmeyi kaldır ve yeniden değerlendir</Menu.Item>
                        </Menu.Dropdown>
                      </Menu>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {pages > 1 && <Pagination mt="md" total={pages} value={page} onChange={setPage} />}
      <ManualPayment opened={manual} onClose={() => setManual(false)} siteId={siteId} />
    </>
  )
}

function ManualPayment({ opened, onClose, siteId }: { opened: boolean; onClose: () => void; siteId: number }) {
  const qc = useQueryClient()
  const [unit, setUnit] = useState<string | null>(null)
  const [amount, setAmount] = useState<number | string>('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [category, setCategory] = useState('aidat')
  const [desc, setDesc] = useState('Elden ödeme')
  const save = useMutation({
    mutationFn: () => api.post(`/api/sites/${siteId}/transactions/manual`, { unit_id: Number(unit), amount: String(amount), txn_date: date, category, description: desc }),
    onSuccess: () => {
      notifyOk('Ödeme kaydedildi')
      qc.invalidateQueries()
      onClose()
    },
    onError: notifyError,
  })
  return (
    <Modal opened={opened} onClose={onClose} title="Elden / nakit ödeme">
      <Stack>
        <UnitSelect label="Daire" value={unit} onChange={setUnit} />
        <NumberInput label="Tutar" value={amount} onChange={setAmount} min={0} decimalScale={2} />
        <TextInput label="Tarih" type="date" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
        <Select label="Kategori" value={category} onChange={(v) => setCategory(v ?? 'aidat')} allowDeselect={false}
          data={['aidat', 'demirbas', 'asansor', 'ek_butce', 'diger'].map((v) => ({ value: v, label: CATEGORY_LABELS[v] }))} />
        <TextInput label="Açıklama" value={desc} onChange={(e) => setDesc(e.currentTarget.value)} />
        <Button disabled={!unit || !amount} loading={save.isPending} onClick={() => save.mutate()}>
          Kaydet
        </Button>
      </Stack>
    </Modal>
  )
}
