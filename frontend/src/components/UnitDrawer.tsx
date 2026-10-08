import {
  ActionIcon, Badge, Button, Drawer, Group, ScrollArea, Select, Stack, Table, Tabs, Text, TextInput, Textarea, Tooltip,
} from '@mantine/core'
import { IconDownload, IconStar, IconStarFilled, IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, download, type PayerAlias, type StatementEntry } from '../api'
import { useAuth, useSite } from '../context'
import { CATEGORY_LABELS, dateTR, METHOD_LABELS, periodLabel } from '../format'
import { Loading, MoneyText, notifyError, notifyOk, useUnits } from './common'

const ROLE_OPTIONS = [
  { value: 'owner', label: 'Malik' },
  { value: 'tenant', label: 'Kiracı' },
  { value: 'payer', label: 'Ödeyen' },
  { value: 'former', label: 'Eski' },
]

export function UnitDrawer({ unitId, onClose, focusPeriod }: { unitId: number | null; onClose: () => void; focusPeriod?: string | null }) {
  const units = useUnits()
  const unit = units.data?.find((u) => u.id === unitId)
  const { canWrite } = useAuth()
  const { siteId } = useSite()
  const qc = useQueryClient()
  const [tab, setTab] = useState<string | null>('statement')
  useEffect(() => setTab('statement'), [unitId])

  const st = useQuery({
    queryKey: ['statement', unitId],
    queryFn: () => api.get<{ entries: StatementEntry[] }>(`/api/units/${unitId}/statement`),
    enabled: !!unitId,
  })
  const aliases = useQuery({
    queryKey: ['aliases', siteId],
    queryFn: () => api.get<PayerAlias[]>(`/api/sites/${siteId}/aliases`),
    enabled: !!siteId && !!unitId,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['units'] })
    qc.invalidateQueries({ queryKey: ['statement', unitId] })
  }

  // Bilgiler
  const [roomType, setRoomType] = useState('')
  const [start, setStart] = useState('')
  const [notes, setNotes] = useState('')
  useEffect(() => {
    setRoomType(unit?.room_type ?? '')
    setStart(unit?.aidat_start_period ?? '')
    setNotes(unit?.notes ?? '')
  }, [unit?.id, unit?.room_type, unit?.aidat_start_period, unit?.notes])
  const saveInfo = useMutation({
    mutationFn: () => api.patch(`/api/units/${unitId}`, { room_type: roomType || null, aidat_start_period: start || null, notes: notes || null }),
    onSuccess: () => {
      notifyOk('Daire bilgileri kaydedildi')
      refresh()
    },
    onError: notifyError,
  })

  // Kişiler
  const [newName, setNewName] = useState('')
  const [newRole, setNewRole] = useState('owner')
  const addPerson = useMutation({
    mutationFn: () => api.post(`/api/units/${unitId}/occupancies`, { full_name: newName, role: newRole, is_primary: newRole !== 'former' }),
    onSuccess: () => {
      setNewName('')
      refresh()
    },
    onError: notifyError,
  })
  const patchOcc = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.patch(`/api/occupancies/${id}`, body),
    onSuccess: refresh,
    onError: notifyError,
  })
  const delOcc = useMutation({ mutationFn: (id: number) => api.del(`/api/occupancies/${id}`), onSuccess: refresh, onError: notifyError })

  const entries = st.data?.entries ?? []
  const unitAliases = (aliases.data ?? []).filter((a) => a.targets.some((t) => t.unit_id === unitId))

  return (
    <Drawer
      opened={!!unitId}
      onClose={onClose}
      position="right"
      size="xl"
      title={
        unit && (
          <Group gap="sm">
            <Text fw={700} size="lg">
              {unit.code}
            </Text>
            <Text c="dimmed">{unit.people.map((p) => p.name).join(' / ')}</Text>
            <Badge color={Number(unit.balance) > 0 ? 'red' : 'teal'} variant="light">
              Bakiye <MoneyText value={unit.balance} />
            </Badge>
          </Group>
        )
      }
    >
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List mb="md">
          <Tabs.Tab value="statement">Hesap ekstresi</Tabs.Tab>
          <Tabs.Tab value="people">Kişiler</Tabs.Tab>
          <Tabs.Tab value="info">Bilgiler</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="statement">
          <Group justify="space-between" mb="xs">
            <Text size="sm" c="dimmed">
              Borç = tahakkuk, alacak = ödeme. Pozitif bakiye borçtur.
            </Text>
            <Button
              size="xs"
              variant="default"
              leftSection={<IconDownload size={14} />}
              onClick={() => download(`/api/units/${unitId}/export/statement.xlsx`, 'ekstre.xlsx').catch(notifyError)}
            >
              Excel
            </Button>
          </Group>
          {st.isLoading ? (
            <Loading />
          ) : (
            <ScrollArea h="calc(100vh - 220px)">
              <Table striped fz="sm" stickyHeader>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Tarih</Table.Th>
                    <Table.Th>Tür</Table.Th>
                    <Table.Th>Açıklama</Table.Th>
                    <Table.Th className="num">Borç</Table.Th>
                    <Table.Th className="num">Alacak</Table.Th>
                    <Table.Th className="num">Bakiye</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {entries.map((e) => (
                    <Table.Tr
                      key={`${e.kind}-${e.id}`}
                      style={focusPeriod && e.period === focusPeriod ? { outline: '2px solid var(--mantine-color-teal-5)' } : undefined}
                    >
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>{e.kind === 'charge' ? periodLabel(e.period, true) : dateTR(e.date)}</Table.Td>
                      <Table.Td miw={90}>
                        <Badge size="xs" variant={e.kind === 'charge' ? 'outline' : 'light'} color={e.kind === 'charge' ? 'gray' : 'teal'} style={{ overflow: 'visible' }}>
                          {CATEGORY_LABELS[e.type] ?? e.type}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" lineClamp={2}>
                          {e.description}
                        </Text>
                        {e.method && (
                          <Text size="10px" c="dimmed">
                            {METHOD_LABELS[e.method] ?? e.method}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td className="num">{Number(e.debit) ? <MoneyText value={e.debit} /> : ''}</Table.Td>
                      <Table.Td className="num">{Number(e.credit) ? <MoneyText value={e.credit} /> : ''}</Table.Td>
                      <Table.Td className="num">
                        <MoneyText value={e.balance} colored />
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="people">
          <Stack>
            <Table>
              <Table.Tbody>
                {unit?.people.map((p) => (
                  <Table.Tr key={p.occupancy_id}>
                    <Table.Td>
                      <Group gap={6}>
                        <Tooltip label={p.is_primary ? 'Birincil (güncel sorumlu)' : 'Birincil yap'}>
                          <ActionIcon
                            variant="subtle"
                            disabled={!canWrite || p.is_primary}
                            onClick={() => patchOcc.mutate({ id: p.occupancy_id, body: { is_primary: true } })}
                            aria-label="Birincil yap"
                          >
                            {p.is_primary ? <IconStarFilled size={16} /> : <IconStar size={16} />}
                          </ActionIcon>
                        </Tooltip>
                        <Text>{p.name}</Text>
                      </Group>
                    </Table.Td>
                    <Table.Td w={140}>
                      <Select
                        size="xs"
                        data={ROLE_OPTIONS}
                        value={p.role}
                        disabled={!canWrite}
                        onChange={(v) => v && patchOcc.mutate({ id: p.occupancy_id, body: { role: v } })}
                        allowDeselect={false}
                        aria-label="Rol"
                      />
                    </Table.Td>
                    <Table.Td w={40}>
                      {canWrite && (
                        <ActionIcon variant="subtle" color="red" onClick={() => delOcc.mutate(p.occupancy_id)} aria-label="Kaldır">
                          <IconTrash size={16} />
                        </ActionIcon>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {canWrite && (
              <Group align="flex-end">
                <TextInput label="Kişi ekle" placeholder="Ad Soyad" value={newName} onChange={(e) => setNewName(e.currentTarget.value)} style={{ flex: 1 }} />
                <Select data={ROLE_OPTIONS} value={newRole} onChange={(v) => setNewRole(v ?? 'owner')} w={120} allowDeselect={false} />
                <Button disabled={!newName.trim()} loading={addPerson.isPending} onClick={() => addPerson.mutate()}>
                  Ekle
                </Button>
              </Group>
            )}
            <Text size="sm" fw={600} mt="md">
              Bu daireye bağlı gönderenler (öğrenilmiş)
            </Text>
            {unitAliases.length === 0 && (
              <Text size="sm" c="dimmed">
                Henüz yok. İnceleme kuyruğunda onayladığınız gönderenler burada görünür.
              </Text>
            )}
            {unitAliases.map((a) => (
              <Group key={a.id} gap="xs">
                <Text size="sm">{a.display_name}</Text>
                <Badge size="xs" variant="light">
                  {a.mode === 'split' ? `bölüştürme: ${a.targets.map((t) => t.code).join(' + ')}` : a.mode === 'ambiguous' ? 'belirsiz' : 'tek daire'}
                </Badge>
                <Text size="xs" c="dimmed">
                  {a.confirm_count} onay · {a.auto_count} otomatik
                </Text>
              </Group>
            ))}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="info">
          <Stack>
            <TextInput label="Oda tipi" placeholder="3+1" description="Oda tipine göre tarife tanımlıysa aidat buna göre hesaplanır" value={roomType} onChange={(e) => setRoomType(e.currentTarget.value)} disabled={!canWrite} />
            <TextInput label="Aidat başlangıç ayı" placeholder="2024-06" value={start} onChange={(e) => setStart(e.currentTarget.value)} disabled={!canWrite} />
            <Textarea label="Notlar" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} autosize minRows={2} disabled={!canWrite} />
            {unit && Object.keys(unit.legacy_tags ?? {}).length > 0 && (
              <Stack gap={2}>
                <Text size="sm" fw={600}>
                  Eski Excel'den notlar (hesaba katılmaz)
                </Text>
                {Object.entries(unit.legacy_tags).map(([k, v]) => (
                  <Text key={k} size="xs" c="dimmed">
                    {k}: {String(v)}
                  </Text>
                ))}
              </Stack>
            )}
            {canWrite && (
              <Button onClick={() => saveInfo.mutate()} loading={saveInfo.isPending} w="fit-content">
                Kaydet
              </Button>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Drawer>
  )
}
