import {
  ActionIcon, Alert, Badge, Button, Card, Divider, Group, List, Modal, NumberInput, ScrollArea, SimpleGrid, Stack, Table,
  TagsInput, Tabs, Text, TextInput,
} from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { IconFileSpreadsheet, IconPlus, IconTrash, IconUpload } from '@tabler/icons-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type SiteDetail, type TrackingPreview } from '../api'
import { ErrorAlert, MoneyText, notifyError, notifyOk, PageHeader } from '../components/common'
import { useAuth, useSite } from '../context'
import { periodLabel } from '../format'

const XLSX_MIME = ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel']

export default function Sites() {
  const { sites, setSiteId, siteId } = useSite()
  const { canWrite } = useAuth()
  const [wizard, setWizard] = useState(false)
  const [importer, setImporter] = useState(false)

  return (
    <>
      <PageHeader
        title="Siteler"
        description="Yönetilen siteler. Yeni siteyi elle tanımlayabilir ya da mevcut takip Excel'inden (bloklar, daireler, sakinler, geçmiş ödemeler) oluşturabilirsiniz."
        actions={
          canWrite && (
            <>
              <Button variant="default" leftSection={<IconFileSpreadsheet size={18} />} onClick={() => setImporter(true)}>
                Takip Excel'inden
              </Button>
              <Button leftSection={<IconPlus size={18} />} onClick={() => setWizard(true)}>
                Yeni site
              </Button>
            </>
          )
        }
      />
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {sites.map((s) => (
          <Card key={s.id} withBorder padding="lg">
            <Group justify="space-between" mb="xs">
              <Text fw={600}>{s.name}</Text>
              {s.id === siteId && <Badge variant="light">Seçili</Badge>}
            </Group>
            <Text size="sm" c="dimmed">
              {s.unit_count ?? 0} daire · kod: {s.code}
            </Text>
            {s.legacy_cutoff_period && (
              <Text size="sm" c="dimmed">
                Excel kesimi: {periodLabel(s.legacy_cutoff_period)}
              </Text>
            )}
            <Button mt="md" variant="light" onClick={() => setSiteId(s.id)} disabled={s.id === siteId}>
              Bu siteyle çalış
            </Button>
          </Card>
        ))}
      </SimpleGrid>
      {sites.length === 0 && <Alert color="blue">Henüz site yok. Sağ üstten yeni site ekleyin.</Alert>}
      <SiteWizard opened={wizard} onClose={() => setWizard(false)} />
      <TrackingImport opened={importer} onClose={() => setImporter(false)} />
    </>
  )
}

interface BlockDraft {
  name: string
  unit_count: number
  room_type: string
  aliases: string[]
}

function SiteWizard({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { setSiteId } = useSite()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [start, setStart] = useState('')
  const [ibans, setIbans] = useState<string[]>([])
  const [blocks, setBlocks] = useState<BlockDraft[]>([{ name: 'A', unit_count: 8, room_type: '', aliases: [] }])
  const [amount, setAmount] = useState<number | string>('')
  const [roomTariffs, setRoomTariffs] = useState<{ room_type: string; amount: number | string }[]>([])

  const save = useMutation({
    mutationFn: () =>
      api.post<SiteDetail>('/api/sites', {
        name,
        address: address || null,
        aidat_start_period: start || null,
        ibans,
        blocks: blocks.filter((b) => b.name.trim()).map((b) => ({ ...b, room_type: b.room_type || null })),
        default_amount: amount === '' ? null : String(amount),
        room_type_tariffs: roomTariffs.filter((r) => r.room_type && r.amount !== '').map((r) => ({ room_type: r.room_type, amount: String(r.amount) })),
        tariff_valid_from: start || null,
      }),
    onSuccess: (site) => {
      qc.invalidateQueries({ queryKey: ['sites'] })
      setSiteId(site.id)
      notifyOk(`${site.name} oluşturuldu`)
      onClose()
      navigate('/')
    },
    onError: notifyError,
  })

  const roomTypes = Array.from(new Set(blocks.map((b) => b.room_type).filter(Boolean)))
  const update = (i: number, patch: Partial<BlockDraft>) => setBlocks(blocks.map((b, j) => (i === j ? { ...b, ...patch } : b)))

  return (
    <Modal opened={opened} onClose={onClose} title="Yeni site" size="xl">
      <Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput label="Site adı" required value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <TextInput
            label="Aidat başlangıç ayı"
            placeholder="2026-01"
            description="YYYY-AA biçiminde"
            value={start}
            onChange={(e) => setStart(e.currentTarget.value)}
          />
        </SimpleGrid>
        <TextInput label="Adres" value={address} onChange={(e) => setAddress(e.currentTarget.value)} />
        <TagsInput
          label="Banka hesapları (IBAN)"
          description="Ekstre yüklendiğinde site IBAN'dan otomatik tanınır. Enter ile ekleyin."
          value={ibans}
          onChange={setIbans}
          placeholder="TR.."
        />
        <Divider label="Bloklar" labelPosition="left" />
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Blok adı</Table.Th>
              <Table.Th>Daire sayısı</Table.Th>
              <Table.Th>Oda tipi</Table.Th>
              <Table.Th>Takma adlar</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {blocks.map((b, i) => (
              <Table.Tr key={i}>
                <Table.Td>
                  <TextInput value={b.name} onChange={(e) => update(i, { name: e.currentTarget.value })} w={90} />
                </Table.Td>
                <Table.Td>
                  <NumberInput value={b.unit_count} min={1} max={500} onChange={(v) => update(i, { unit_count: Number(v) || 1 })} w={100} />
                </Table.Td>
                <Table.Td>
                  <TextInput placeholder="3+1" value={b.room_type} onChange={(e) => update(i, { room_type: e.currentTarget.value })} w={90} />
                </Table.Td>
                <Table.Td>
                  <TagsInput value={b.aliases} onChange={(v) => update(i, { aliases: v })} placeholder="ör. A-1, 5/1A" />
                </Table.Td>
                <Table.Td>
                  <ActionIcon variant="subtle" color="red" onClick={() => setBlocks(blocks.filter((_, j) => j !== i))} aria-label="Sil">
                    <IconTrash size={16} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Button variant="subtle" leftSection={<IconPlus size={16} />} onClick={() => setBlocks([...blocks, { name: '', unit_count: 8, room_type: '', aliases: [] }])}>
          Blok ekle
        </Button>
        <Divider label="Aidat tarifesi" labelPosition="left" />
        <NumberInput
          label="Tüm daireler için aylık aidat (TL)"
          description="Oda tipine göre farklı tutar varsa aşağıdan ekleyin; daire bazında sonra da tanımlanabilir."
          value={amount}
          onChange={setAmount}
          min={0}
          thousandSeparator="."
          decimalSeparator=","
        />
        {roomTariffs.map((r, i) => (
          <Group key={i} grow>
            <TextInput label="Oda tipi" value={r.room_type} onChange={(e) => setRoomTariffs(roomTariffs.map((x, j) => (i === j ? { ...x, room_type: e.currentTarget.value } : x)))} />
            <NumberInput label="Tutar" value={r.amount} onChange={(v) => setRoomTariffs(roomTariffs.map((x, j) => (i === j ? { ...x, amount: v } : x)))} />
          </Group>
        ))}
        <Group>
          <Button
            variant="subtle"
            size="xs"
            onClick={() => setRoomTariffs([...roomTariffs, { room_type: roomTypes.find((t) => !roomTariffs.some((r) => r.room_type === t)) ?? '', amount: '' }])}
          >
            Oda tipine göre tutar ekle
          </Button>
        </Group>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Vazgeç
          </Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!name.trim() || blocks.length === 0}>
            Siteyi oluştur
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

function TrackingImport({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { setSiteId, sites } = useSite()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [target, setTarget] = useState<'new' | string>('new')
  const [siteName, setSiteName] = useState('')
  const [cutoff, setCutoff] = useState('')
  const [startYear, setStartYear] = useState<number | string>('')
  const [preview, setPreview] = useState<TrackingPreview | null>(null)
  const [error, setError] = useState<unknown>(null)

  const fields = () => ({
    site_id: target === 'new' ? undefined : target,
    site_name: target === 'new' ? siteName : undefined,
    cutoff: cutoff || undefined,
    start_year: startYear === '' ? undefined : startYear,
  })

  const doPreview = useMutation({
    mutationFn: (f: File) => api.upload<TrackingPreview>('/api/imports/tracking/preview', f, fields()),
    onSuccess: (p) => {
      setPreview(p)
      setCutoff(p.cutoff)
      setStartYear(p.start_year)
      setError(null)
    },
    onError: setError,
  })
  const commit = useMutation({
    mutationFn: () => api.upload<{ site_id: number; legacy_payments: number; units: number }>('/api/imports/tracking/commit', file!, fields()),
    onSuccess: (r) => {
      qc.invalidateQueries()
      setSiteId(r.site_id)
      notifyOk(`${r.units} daire ve ${r.legacy_payments} eski ödeme içe aktarıldı. Sırada: tarife ve açılış bakiyesi.`)
      onClose()
      navigate('/acilis')
    },
    onError: setError,
  })

  const pick = (files: File[]) => {
    const f = files[0]
    setFile(f)
    if (target === 'new' && !siteName) setSiteName(f.name.replace(/\.xlsx?$/i, '').replace(/^\d+\s*-\s*/, '').replace(/-\d+$/, ''))
    setPreview(null)
  }

  return (
    <Modal opened={opened} onClose={onClose} title="Takip Excel'inden içe aktar" size="xl">
      <Stack>
        <Text size="sm" c="dimmed">
          "GELİR" gibi bir sayfada blok başlıkları (ör. <b>A-1 BLOK</b> + ay adları), altında daire no ve sakin adları ile aylık
          ödemeler bekleniyor. Kesim ayından <b>önceki</b> ödemeler geçmiş olarak alınır; kesimden sonrası banka ekstresinden gelir
          ve sadece mutabakat için saklanır (çift sayım olmaz).
        </Text>
        <Tabs value={target === 'new' ? 'new' : 'existing'} onChange={(v) => setTarget(v === 'new' ? 'new' : String(sites[0]?.id ?? 'new'))}>
          <Tabs.List>
            <Tabs.Tab value="new">Yeni site</Tabs.Tab>
            <Tabs.Tab value="existing" disabled={sites.length === 0}>
              Mevcut siteyi güncelle
            </Tabs.Tab>
          </Tabs.List>
        </Tabs>
        {target === 'new' ? (
          <TextInput label="Site adı" value={siteName} onChange={(e) => setSiteName(e.currentTarget.value)} required />
        ) : (
          <Group>
            {sites.map((s) => (
              <Button key={s.id} variant={String(s.id) === target ? 'filled' : 'default'} size="xs" onClick={() => setTarget(String(s.id))}>
                {s.name}
              </Button>
            ))}
          </Group>
        )}
        <Dropzone onDrop={pick} accept={XLSX_MIME} maxFiles={1} maxSize={15 * 1024 ** 2}>
          <Group justify="center" gap="sm" mih={80} style={{ pointerEvents: 'none' }}>
            <IconUpload size={28} />
            <Text>{file ? file.name : 'Excel dosyasını sürükleyin ya da tıklayın'}</Text>
          </Group>
        </Dropzone>
        <SimpleGrid cols={2}>
          <TextInput label="Kesim ayı" description="Banka ekstresinin başladığı ay (YYYY-AA)" value={cutoff} onChange={(e) => setCutoff(e.currentTarget.value)} />
          <NumberInput label="İlk ay sütununun yılı" description="Excel'de yıl yazmadığı için tahmin edilir" value={startYear} onChange={setStartYear} />
        </SimpleGrid>
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" disabled={!file} loading={doPreview.isPending} onClick={() => file && doPreview.mutate(file)}>
            Önizle
          </Button>
          <Button disabled={!preview} loading={commit.isPending} onClick={() => commit.mutate()}>
            İçe aktar
          </Button>
        </Group>
        {preview && <PreviewView p={preview} />}
      </Stack>
    </Modal>
  )
}

function PreviewView({ p }: { p: TrackingPreview }) {
  return (
    <Stack gap="xs">
      <Text size="sm">
        Sayfa <b>{p.sheet}</b> · {p.unit_count} daire ({p.blocks.map((b) => `${b.name}: ${b.unit_count}`).join(', ')}) · sütunlar{' '}
        {periodLabel(p.first_period)} – {periodLabel(p.last_period)} · kesim {periodLabel(p.cutoff)}
      </Text>
      <Text size="sm">
        Geçmiş olarak alınacak: <MoneyText value={p.legacy_total} fw={600} /> · Kesim sonrası (mutabakat): <MoneyText value={p.post_cutoff_total} />
      </Text>
      {p.warnings.length > 0 && (
        <Alert color="yellow" title="Uyarılar">
          <List size="sm">
            {p.warnings.map((w) => (
              <List.Item key={w}>{w}</List.Item>
            ))}
          </List>
        </Alert>
      )}
      <ScrollArea h={300}>
        <Table striped withTableBorder fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Daire</Table.Th>
              <Table.Th>Kişiler (son = güncel)</Table.Th>
              <Table.Th>İlk ödeme</Table.Th>
              <Table.Th className="num">Geçmiş</Table.Th>
              <Table.Th className="num">Kesim sonrası</Table.Th>
              <Table.Th>Not</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {p.units.map((u) => (
              <Table.Tr key={u.code}>
                <Table.Td fw={600}>{u.code}</Table.Td>
                <Table.Td>{u.names.join(' → ')}</Table.Td>
                <Table.Td>{periodLabel(u.first_period, true)}</Table.Td>
                <Table.Td className="num">
                  <MoneyText value={u.legacy_total} />
                </Table.Td>
                <Table.Td className="num">
                  <MoneyText value={u.post_cutoff_total} />
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {Object.entries(u.expressions).map(([k, v]) => `${k}: ${v}`).join('; ')}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      {p.notes.length > 0 && (
        <Alert color="gray" title="Excel'deki notlar (hesaba katılmaz)">
          <List size="xs">
            {p.notes.map((n) => (
              <List.Item key={n}>{n}</List.Item>
            ))}
          </List>
        </Alert>
      )}
    </Stack>
  )
}
