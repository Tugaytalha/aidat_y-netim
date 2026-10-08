import {
  ActionIcon, Badge, Button, Card, Group, Modal, MultiSelect, NumberInput, PasswordInput, Select, Slider, Stack, Switch, Table, TagsInput,
  Tabs, Text, TextInput, Title,
} from '@mantine/core'
import { modals } from '@mantine/modals'
import { IconPlus, IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type PayerAlias, type SiteDetail, type User } from '../api'
import { ErrorAlert, Loading, NoSite, notifyError, notifyOk, PageHeader } from '../components/common'
import { useAuth, useSite } from '../context'
import { dateTR } from '../format'

export default function Settings() {
  const { siteId } = useSite()
  const { user } = useAuth()
  const detail = useQuery({ queryKey: ['site', siteId], queryFn: () => api.get<SiteDetail>(`/api/sites/${siteId}`), enabled: !!siteId })
  if (!siteId) return <NoSite />
  return (
    <>
      <PageHeader title="Site ayarları" description="Genel ayarlar, bloklar ve banka açıklamalarında kullanılan takma adlar, hesaplar, öğrenilmiş gönderenler." />
      <ErrorAlert error={detail.error} />
      {detail.isLoading || !detail.data ? (
        <Loading />
      ) : (
        <Tabs defaultValue="general">
          <Tabs.List mb="md">
            <Tabs.Tab value="general">Genel</Tabs.Tab>
            <Tabs.Tab value="blocks">Bloklar ve takma adlar</Tabs.Tab>
            <Tabs.Tab value="accounts">Banka hesapları</Tabs.Tab>
            <Tabs.Tab value="aliases">Gönderen hafızası</Tabs.Tab>
            {user?.role === 'admin' && <Tabs.Tab value="users">Kullanıcılar</Tabs.Tab>}
            <Tabs.Tab value="audit">Denetim kaydı</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="general"><General site={detail.data} /></Tabs.Panel>
          <Tabs.Panel value="blocks"><Blocks site={detail.data} /></Tabs.Panel>
          <Tabs.Panel value="accounts"><Accounts site={detail.data} /></Tabs.Panel>
          <Tabs.Panel value="aliases"><Aliases siteId={siteId} /></Tabs.Panel>
          {user?.role === 'admin' && <Tabs.Panel value="users"><Users /></Tabs.Panel>}
          <Tabs.Panel value="audit"><Audit siteId={siteId} /></Tabs.Panel>
        </Tabs>
      )}
    </>
  )
}

function useRefresh() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['site'] })
    qc.invalidateQueries({ queryKey: ['sites'] })
    qc.invalidateQueries({ queryKey: ['units'] })
  }
}

function General({ site }: { site: SiteDetail }) {
  const { canWrite } = useAuth()
  const refresh = useRefresh()
  const [name, setName] = useState(site.name)
  const [address, setAddress] = useState(site.address ?? '')
  const [start, setStart] = useState(site.aidat_start_period ?? '')
  const [cutoff, setCutoff] = useState(site.legacy_cutoff_period ?? '')
  const [llm, setLlm] = useState(site.llm_enabled)
  const [threshold, setThreshold] = useState(site.auto_match_threshold ?? 0.9)
  useEffect(() => {
    setName(site.name)
    setLlm(site.llm_enabled)
  }, [site])
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/api/sites/${site.id}`, {
        name, address: address || null, aidat_start_period: start || null, legacy_cutoff_period: cutoff || null, llm_enabled: llm, auto_match_threshold: threshold,
      }),
    onSuccess: () => {
      notifyOk('Kaydedildi')
      refresh()
    },
    onError: notifyError,
  })
  return (
    <Card withBorder padding="lg" maw={640}>
      <Stack>
        <TextInput label="Site adı" value={name} onChange={(e) => setName(e.currentTarget.value)} disabled={!canWrite} />
        <TextInput label="Adres" value={address} onChange={(e) => setAddress(e.currentTarget.value)} disabled={!canWrite} />
        <Group grow>
          <TextInput label="Aidat başlangıç ayı" placeholder="2023-08" value={start} onChange={(e) => setStart(e.currentTarget.value)} disabled={!canWrite} />
          <TextInput label="Excel kesim ayı" description="Bu aydan önceki banka hareketleri yok sayılır" value={cutoff} onChange={(e) => setCutoff(e.currentTarget.value)} disabled={!canWrite} />
        </Group>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Otomatik eşleştirme eşiği: %{Math.round(threshold * 100)}
          </Text>
          <Text size="xs" c="dimmed">
            Yüksek eşik = daha az otomatik eşleşme, daha çok inceleme. Varsayılan %90.
          </Text>
          <Slider min={0.8} max={0.99} step={0.01} value={threshold} onChange={setThreshold} disabled={!canWrite} label={(v) => `%${Math.round(v * 100)}`} />
        </Stack>
        <Switch
          checked={llm}
          onChange={(e) => setLlm(e.currentTarget.checked)}
          disabled={!canWrite}
          label="AI önerisi (OpenRouter)"
          description="İnceleme kuyruğunda 'AI ile öner' düğmesini açar. Açıklama ve sakin adları OpenRouter'a gönderilir (KVKK açısından değerlendirin); bakiye gönderilmez. Sunucuda OPENROUTER_API_KEY tanımlı olmalı."
        />
        {canWrite && (
          <Button w="fit-content" onClick={() => save.mutate()} loading={save.isPending}>
            Kaydet
          </Button>
        )}
      </Stack>
    </Card>
  )
}

function Blocks({ site }: { site: SiteDetail }) {
  const { canWrite } = useAuth()
  const refresh = useRefresh()
  const [newName, setNewName] = useState('')
  const [newCount, setNewCount] = useState<number | string>(8)
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.patch(`/api/blocks/${id}`, body),
    onSuccess: () => {
      notifyOk('Blok güncellendi')
      refresh()
    },
    onError: notifyError,
  })
  const add = useMutation({
    mutationFn: () => api.post(`/api/sites/${site.id}/blocks`, { name: newName, unit_count: Number(newCount) }),
    onSuccess: () => {
      setNewName('')
      refresh()
    },
    onError: notifyError,
  })
  return (
    <Stack maw={900}>
      <Text size="sm" c="dimmed">
        Takma adlar, banka açıklamalarında bloğun farklı yazımlarıdır. Ör. tek "B" bloğu için sakinler "B1", "B2" yazıyorsa ekleyin; adres numarası
        "5/1C" C1 bloğunu ifade ediyorsa C1'e "5/1c" ekleyin. "A-1", "1A", "A 1" gibi yazımlar zaten otomatik tanınır.
      </Text>
      {site.blocks.map((b) => (
        <BlockRow key={b.id} block={b} canWrite={canWrite} onSave={(body) => patch.mutate({ id: b.id, body })} />
      ))}
      {canWrite && (
        <Group align="flex-end">
          <TextInput label="Yeni blok" value={newName} onChange={(e) => setNewName(e.currentTarget.value)} w={120} />
          <NumberInput label="Daire sayısı" value={newCount} onChange={setNewCount} min={1} w={120} />
          <Button leftSection={<IconPlus size={16} />} disabled={!newName} loading={add.isPending} onClick={() => add.mutate()}>
            Blok ekle
          </Button>
        </Group>
      )}
    </Stack>
  )
}

function BlockRow({ block, canWrite, onSave }: { block: SiteDetail['blocks'][number]; canWrite: boolean; onSave: (b: Record<string, unknown>) => void }) {
  const [aliases, setAliases] = useState(block.aliases)
  const [addUnits, setAddUnits] = useState<number | string>('')
  useEffect(() => setAliases(block.aliases), [block.aliases])
  return (
    <Card withBorder padding="sm">
      <Group align="flex-end" wrap="wrap">
        <Stack gap={0} w={90}>
          <Text fw={700}>{block.name}</Text>
          <Text size="xs" c="dimmed">
            {block.units.length} daire
          </Text>
        </Stack>
        <TagsInput label="Takma adlar" value={aliases} onChange={setAliases} disabled={!canWrite} style={{ flex: 1, minWidth: 220 }} placeholder="Enter ile ekleyin" />
        <NumberInput label="Daire ekle" value={addUnits} onChange={setAddUnits} min={1} max={100} w={100} disabled={!canWrite} />
        {canWrite && (
          <Button variant="light" onClick={() => onSave({ aliases, ...(addUnits ? { add_units: Number(addUnits) } : {}) })}>
            Kaydet
          </Button>
        )}
      </Group>
    </Card>
  )
}

function Accounts({ site }: { site: SiteDetail }) {
  const { canWrite } = useAuth()
  const refresh = useRefresh()
  const [iban, setIban] = useState('')
  const [bank, setBank] = useState('')
  const add = useMutation({
    mutationFn: () => api.post(`/api/sites/${site.id}/bank-accounts`, { iban, bank_name: bank || null }),
    onSuccess: () => {
      setIban('')
      refresh()
    },
    onError: notifyError,
  })
  return (
    <Stack maw={700}>
      <Table>
        <Table.Tbody>
          {site.bank_accounts.map((a) => (
            <Table.Tr key={a.id}>
              <Table.Td ff="monospace">{a.iban}</Table.Td>
              <Table.Td>{a.bank_name}</Table.Td>
              <Table.Td>{a.account_no}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {site.bank_accounts.length === 0 && <Text c="dimmed">Tanımlı hesap yok. İlk ekstre yüklendiğinde IBAN otomatik eklenebilir.</Text>}
      {canWrite && (
        <Group align="flex-end">
          <TextInput label="IBAN" value={iban} onChange={(e) => setIban(e.currentTarget.value)} w={300} />
          <TextInput label="Banka" value={bank} onChange={(e) => setBank(e.currentTarget.value)} />
          <Button disabled={!iban} loading={add.isPending} onClick={() => add.mutate()}>
            Ekle
          </Button>
        </Group>
      )}
    </Stack>
  )
}

function Aliases({ siteId }: { siteId: number }) {
  const { canWrite } = useAuth()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['aliases', siteId], queryFn: () => api.get<PayerAlias[]>(`/api/sites/${siteId}/aliases`) })
  const del = useMutation({
    mutationFn: (id: number) => api.del(`/api/aliases/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aliases', siteId] }),
    onError: notifyError,
  })
  const MODE: Record<string, string> = { single: 'Tek daire', split: 'Bölüştürme', ambiguous: 'Belirsiz' }
  const SRC: Record<string, string> = { manual: 'Onaylı', auto: 'Otomatik', excel: 'Excel' }
  return (
    <>
      <Text size="sm" c="dimmed" mb="sm">
        Bankadaki gönderen adı → daire. Onayladığınız eşleşmeler burada saklanır ve sonraki ekstrelerde otomatik uygulanır. Yanlış bir kaydı silin.
      </Text>
      {q.isLoading ? (
        <Loading />
      ) : (
        <Table.ScrollContainer minWidth={700}>
          <Table striped fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Gönderen</Table.Th>
                <Table.Th>Daire(ler)</Table.Th>
                <Table.Th>Tür</Table.Th>
                <Table.Th>Kaynak</Table.Th>
                <Table.Th>Kullanım</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {q.data?.map((a) => (
                <Table.Tr key={a.id}>
                  <Table.Td>{a.display_name}</Table.Td>
                  <Table.Td>
                    {a.targets.map((t) => (
                      <Badge key={t.unit_id} mr={4} variant="light">
                        {t.code}
                        {a.mode === 'split' && t.ratio ? ` %${Math.round(t.ratio * 100)}` : ''}
                      </Badge>
                    ))}
                  </Table.Td>
                  <Table.Td>{MODE[a.mode]}</Table.Td>
                  <Table.Td>{SRC[a.source] ?? a.source}</Table.Td>
                  <Table.Td>
                    {a.confirm_count} onay · {a.auto_count} oto.
                  </Table.Td>
                  <Table.Td>
                    {canWrite && (
                      <ActionIcon variant="subtle" color="red" aria-label="Sil"
                        onClick={() => modals.openConfirmModal({ title: 'Hafıza kaydı silinsin mi?', children: <Text size="sm">{a.display_name} artık otomatik eşleşmez.</Text>, onConfirm: () => del.mutate(a.id) })}>
                        <IconTrash size={16} />
                      </ActionIcon>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </>
  )
}

function Users() {
  const qc = useQueryClient()
  const { sites } = useSite()
  const q = useQuery({ queryKey: ['users'], queryFn: () => api.get<User[]>('/api/users') })
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('operator')
  const [siteIds, setSiteIds] = useState<string[]>([])
  const create = useMutation({
    mutationFn: () => api.post('/api/users', { email, full_name: fullName, password, role, site_ids: siteIds.map(Number) }),
    onSuccess: () => {
      setOpen(false)
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: notifyError,
  })
  const toggle = useMutation({
    mutationFn: (u: User) => api.patch(`/api/users/${u.id}`, { is_active: !u.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
    onError: notifyError,
  })
  const ROLE: Record<string, string> = { admin: 'Yönetici', operator: 'Operatör', viewer: 'Görüntüleyici' }
  return (
    <Stack maw={800}>
      <Group justify="space-between">
        <Title order={5}>Kullanıcılar</Title>
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setOpen(true)}>
          Kullanıcı ekle
        </Button>
      </Group>
      <Table striped>
        <Table.Tbody>
          {q.data?.map((u) => (
            <Table.Tr key={u.id}>
              <Table.Td>{u.full_name || '—'}</Table.Td>
              <Table.Td>{u.email}</Table.Td>
              <Table.Td>{ROLE[u.role]}</Table.Td>
              <Table.Td>{u.role === 'admin' ? 'Tüm siteler' : (u.site_ids ?? []).map((id) => sites.find((s) => s.id === id)?.name ?? id).join(', ')}</Table.Td>
              <Table.Td>
                <Switch size="xs" checked={u.is_active} onChange={() => toggle.mutate(u)} label={u.is_active ? 'Aktif' : 'Pasif'} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Modal opened={open} onClose={() => setOpen(false)} title="Yeni kullanıcı">
        <Stack>
          <TextInput label="Ad soyad" value={fullName} onChange={(e) => setFullName(e.currentTarget.value)} />
          <TextInput label="E-posta" value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
          <PasswordInput label="Şifre" value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
          <Select label="Rol" value={role} onChange={(v) => setRole(v ?? 'operator')} allowDeselect={false}
            data={[{ value: 'admin', label: 'Yönetici' }, { value: 'operator', label: 'Operatör' }, { value: 'viewer', label: 'Görüntüleyici' }]} />
          {role !== 'admin' && (
            <MultiSelect label="Erişebileceği siteler" data={sites.map((s) => ({ value: String(s.id), label: s.name }))} value={siteIds} onChange={setSiteIds} />
          )}
          <Button disabled={!email || password.length < 6} loading={create.isPending} onClick={() => create.mutate()}>
            Oluştur
          </Button>
        </Stack>
      </Modal>
    </Stack>
  )
}

function Audit({ siteId }: { siteId: number }) {
  const q = useQuery({
    queryKey: ['audit', siteId],
    queryFn: () => api.get<{ id: number; user: string | null; action: string; entity: string; data: Record<string, unknown>; created_at: string }[]>(`/api/sites/${siteId}/audit`),
  })
  return q.isLoading ? (
    <Loading />
  ) : (
    <Table.ScrollContainer minWidth={700}>
      <Table striped fz="xs">
        <Table.Tbody>
          {q.data?.map((a) => (
            <Table.Tr key={a.id}>
              <Table.Td style={{ whiteSpace: 'nowrap' }}>{dateTR(a.created_at)} {a.created_at.slice(11, 16)}</Table.Td>
              <Table.Td>{a.user}</Table.Td>
              <Table.Td>
                {a.entity} · {a.action}
              </Table.Td>
              <Table.Td>
                <Text size="xs" c="dimmed" lineClamp={2}>
                  {JSON.stringify(a.data)}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
