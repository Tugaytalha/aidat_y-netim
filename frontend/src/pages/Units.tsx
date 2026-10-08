import { Badge, Button, Checkbox, Group, Modal, Stack, Table, Text, TextInput } from '@mantine/core'
import { IconSearch } from '@tabler/icons-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { ErrorAlert, Loading, MoneyText, NoSite, notifyError, notifyOk, PageHeader, useUnits } from '../components/common'
import { UnitDrawer } from '../components/UnitDrawer'
import { useAuth, useSite } from '../context'
import { fold } from '../components/TxnParts'

export default function Units() {
  const { siteId } = useSite()
  const { canWrite } = useAuth()
  const units = useUnits()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [bulkOpen, setBulkOpen] = useState(false)
  const [roomType, setRoomType] = useState('')
  const bulk = useMutation({
    mutationFn: () => api.post<{ changed: number }>(`/api/sites/${siteId}/units/bulk`, { unit_ids: selected, room_type: roomType }),
    onSuccess: (r) => {
      notifyOk(`${r.changed} dairenin oda tipi güncellendi`)
      setBulkOpen(false)
      setSelected([])
      qc.invalidateQueries({ queryKey: ['units'] })
    },
    onError: notifyError,
  })

  if (!siteId) return <NoSite />
  const s = fold(search.trim())
  const rows = (units.data ?? []).filter(
    (u) => !s || fold(u.code).includes(s) || u.people.some((p) => fold(p.name).includes(s)),
  )

  return (
    <>
      <PageHeader
        title="Daireler"
        description="Sakinler, oda tipleri ve bakiyeler. Bir satıra tıklayınca hesap ekstresi açılır."
        actions={
          <>
            <TextInput leftSection={<IconSearch size={16} />} placeholder="Daire ya da kişi ara" value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
            {canWrite && (
              <Button variant="default" disabled={!selected.length} onClick={() => setBulkOpen(true)}>
                Oda tipi ata ({selected.length})
              </Button>
            )}
          </>
        }
      />
      <ErrorAlert error={units.error} />
      {units.isLoading ? (
        <Loading />
      ) : (
        <Table.ScrollContainer minWidth={760}>
          <Table highlightOnHover striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={36}>
                  <Checkbox
                    aria-label="Tümünü seç"
                    checked={selected.length > 0 && selected.length === rows.length}
                    indeterminate={selected.length > 0 && selected.length < rows.length}
                    onChange={(e) => setSelected(e.currentTarget.checked ? rows.map((r) => r.id) : [])}
                  />
                </Table.Th>
                <Table.Th>Daire</Table.Th>
                <Table.Th>Sakin(ler)</Table.Th>
                <Table.Th>Oda tipi</Table.Th>
                <Table.Th className="num">Tahakkuk</Table.Th>
                <Table.Th className="num">Ödenen</Table.Th>
                <Table.Th className="num">Bakiye</Table.Th>
                <Table.Th>Geciken</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((u) => (
                <Table.Tr key={u.id} style={{ cursor: 'pointer' }} onClick={() => setOpen(u.id)}>
                  <Table.Td onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      aria-label={`${u.code} seç`}
                      checked={selected.includes(u.id)}
                      onChange={(e) => setSelected(e.currentTarget.checked ? [...selected, u.id] : selected.filter((x) => x !== u.id))}
                    />
                  </Table.Td>
                  <Table.Td fw={600}>{u.code}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{u.people.filter((p) => p.role !== 'former').map((p) => p.name).join(' / ') || '—'}</Text>
                    {u.people.some((p) => p.role === 'former') && (
                      <Text size="xs" c="dimmed">
                        eski: {u.people.filter((p) => p.role === 'former').map((p) => p.name).join(', ')}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>{u.room_type ?? '—'}</Table.Td>
                  <Table.Td className="num">
                    <MoneyText value={u.charged} />
                  </Table.Td>
                  <Table.Td className="num">
                    <MoneyText value={u.paid} />
                  </Table.Td>
                  <Table.Td className="num">
                    <MoneyText value={u.balance} colored fw={600} />
                  </Table.Td>
                  <Table.Td>{u.overdue_months > 0 ? <Badge color="red" variant="light">{u.overdue_months} ay</Badge> : ''}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <UnitDrawer unitId={open} onClose={() => setOpen(null)} />
      <Modal opened={bulkOpen} onClose={() => setBulkOpen(false)} title="Oda tipi ata">
        <Stack>
          <TextInput label="Oda tipi" placeholder="3+1" value={roomType} onChange={(e) => setRoomType(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button loading={bulk.isPending} onClick={() => bulk.mutate()}>
              {selected.length} daireye uygula
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}
