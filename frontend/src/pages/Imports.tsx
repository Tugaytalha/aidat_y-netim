import { Alert, Badge, Button, Card, Group, List, Modal, SimpleGrid, Stack, Table, Tabs, Text } from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { IconCheck, IconFileSpreadsheet, IconUpload } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, type BankImportResult } from '../api'
import { ErrorAlert, MoneyText, NoSite, notifyError, PageHeader } from '../components/common'
import { useAuth, useSite } from '../context'
import { dateTR, periodLabel } from '../format'

const XLSX_MIME = ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel']

interface ImportRow {
  id: number
  kind: string
  file_name: string
  bank_code: string | null
  period_start: string | null
  period_end: string | null
  stats: Partial<BankImportResult> & { units?: number; legacy_payments?: number }
  uploaded_at: string
}

interface UnknownIban {
  detail: string
  iban: string
  account_holder: string | null
  period_start: string | null
  period_end: string | null
  rows: number
}

export default function Imports() {
  const { siteId, site, sites, setSiteId } = useSite()
  const { canWrite } = useAuth()
  const qc = useQueryClient()
  const [result, setResult] = useState<BankImportResult | null>(null)
  const [unknown, setUnknown] = useState<{ file: File; info: UnknownIban } | null>(null)

  const history = useQuery({ queryKey: ['imports', siteId], queryFn: () => api.get<ImportRow[]>(`/api/sites/${siteId}/imports`), enabled: !!siteId })
  const coverage = useQuery({
    queryKey: ['coverage', siteId],
    queryFn: () => api.get<{ iban: string; bank_name: string | null; statements: { file_name: string; start: string; end: string }[]; gaps: { message: string }[] }[]>(`/api/sites/${siteId}/coverage`),
    enabled: !!siteId,
  })

  const upload = useMutation({
    mutationFn: ({ file, site }: { file: File; site?: number }) => api.upload<BankImportResult>('/api/imports/bank', file, { site_id: site }),
    onSuccess: (r) => {
      setResult(r)
      setUnknown(null)
      if (r.site_id !== siteId) setSiteId(r.site_id)
      qc.invalidateQueries()
    },
    onError: (e, vars) => {
      if (e instanceof ApiError && e.status === 409 && (e.data as { code?: string })?.code === 'unknown_iban') {
        setUnknown({ file: vars.file, info: e.data as UnknownIban })
      } else notifyError(e)
    },
  })

  if (!siteId) return <NoSite />

  return (
    <>
      <PageHeader
        title="Banka ekstresi yükle"
        description="Bankadan indirdiğiniz hesap hareketleri Excel'ini yükleyin. Aynı işlem ikinci kez eklenmez; tarih aralıkları çakışan ekstreler güvenle yüklenebilir. Site, IBAN'dan otomatik bulunur."
      />
      {canWrite && (
        <Dropzone onDrop={(files) => upload.mutate({ file: files[0] })} accept={XLSX_MIME} maxFiles={1} maxSize={15 * 1024 ** 2} loading={upload.isPending} mb="lg">
          <Group justify="center" gap="md" mih={110} style={{ pointerEvents: 'none' }}>
            <IconUpload size={36} />
            <Stack gap={2}>
              <Text size="lg">Ekstre dosyasını sürükleyin ya da tıklayın</Text>
              <Text size="sm" c="dimmed">
                .xlsx · Ziraat formatı tanınır, diğer bankalar için Tarih/Açıklama/Tutar sütunları aranır
              </Text>
            </Stack>
          </Group>
        </Dropzone>
      )}

      {result && <ResultCard r={result} />}

      <Tabs defaultValue="history" mt="lg">
        <Tabs.List>
          <Tabs.Tab value="history">Yükleme geçmişi</Tabs.Tab>
          <Tabs.Tab value="coverage">Kapsama ve boşluklar</Tabs.Tab>
          <Tabs.Tab value="recon">Mutabakat (Excel ↔ sistem)</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="history" pt="md">
          <ErrorAlert error={history.error} />
          <Table.ScrollContainer minWidth={700}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Dosya</Table.Th>
                  <Table.Th>Tür</Table.Th>
                  <Table.Th>Aralık</Table.Th>
                  <Table.Th>Sonuç</Table.Th>
                  <Table.Th>Yüklenme</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {history.data?.map((h) => (
                  <Table.Tr key={h.id}>
                    <Table.Td>{h.file_name}</Table.Td>
                    <Table.Td>{h.kind === 'bank_statement' ? `Ekstre (${h.bank_code})` : 'Takip Excel'}</Table.Td>
                    <Table.Td>
                      {dateTR(h.period_start)} – {dateTR(h.period_end)}
                    </Table.Td>
                    <Table.Td>
                      {h.kind === 'bank_statement'
                        ? `${h.stats.new ?? 0} yeni · ${h.stats.duplicates ?? 0} tekrar · ${h.stats.auto_matched ?? 0} otomatik`
                        : `${h.stats.units ?? 0} daire · ${h.stats.legacy_payments ?? 0} eski ödeme`}
                    </Table.Td>
                    <Table.Td>{dateTR(h.uploaded_at)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Tabs.Panel>
        <Tabs.Panel value="coverage" pt="md">
          <Stack>
            {coverage.data?.length === 0 && <Text c="dimmed">Bu siteye tanımlı banka hesabı yok.</Text>}
            {coverage.data?.map((acc) => (
              <Card withBorder key={acc.iban}>
                <Text fw={600}>
                  {acc.iban} {acc.bank_name && <Text span c="dimmed">({acc.bank_name})</Text>}
                </Text>
                <List size="sm" mt="xs">
                  {acc.statements.map((s, i) => (
                    <List.Item key={i}>
                      {dateTR(s.start)} – {dateTR(s.end)} · {s.file_name}
                    </List.Item>
                  ))}
                </List>
                {acc.gaps.length > 0 ? (
                  <Alert color="orange" mt="sm" title="Bakiye zincirinde kopukluk">
                    {acc.gaps.map((g) => (
                      <Text key={g.message} size="sm">
                        {g.message}
                      </Text>
                    ))}
                  </Alert>
                ) : (
                  <Text size="sm" c="teal" mt="xs">
                    <IconCheck size={14} /> Bakiye zinciri kesintisiz
                  </Text>
                )}
              </Card>
            ))}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="recon" pt="md">
          <Reconciliation siteId={siteId} />
        </Tabs.Panel>
      </Tabs>

      <Modal opened={!!unknown} onClose={() => setUnknown(null)} title="Bu hesap henüz bir siteye tanımlı değil">
        {unknown && (
          <Stack>
            <Text size="sm">
              <b>{unknown.info.iban}</b>
              {unknown.info.account_holder && <> · {unknown.info.account_holder}</>}
              <br />
              {dateTR(unknown.info.period_start)} – {dateTR(unknown.info.period_end)} · {unknown.info.rows} hareket
            </Text>
            <Text size="sm">Hangi siteye ait? Seçtiğiniz siteye IBAN eklenir ve sonraki yüklemelerde otomatik tanınır.</Text>
            {sites.map((s) => (
              <Button key={s.id} variant={s.id === site?.id ? 'filled' : 'default'} loading={upload.isPending}
                onClick={() => upload.mutate({ file: unknown.file, site: s.id })} leftSection={<IconFileSpreadsheet size={16} />}>
                {s.name}
              </Button>
            ))}
          </Stack>
        )}
      </Modal>
    </>
  )
}

function ResultCard({ r }: { r: BankImportResult }) {
  if (r.already_imported) {
    return <Alert color="blue" title="Bu dosya daha önce yüklenmiş">Yeni hareket yok; hiçbir şey değişmedi.</Alert>
  }
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="sm">
        <Text fw={600}>
          {dateTR(r.period_start)} – {dateTR(r.period_end)} · {r.total_rows} hareket
        </Text>
        {r.footer_credit_total && Number(r.footer_credit_total) === Number(r.credit_total) ? (
          <Badge color="teal" variant="light">Toplam ekstre özetiyle uyumlu</Badge>
        ) : (
          r.footer_credit_total && <Badge color="red">Toplam uyuşmuyor</Badge>
        )}
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }}>
        <Num label="Yeni" v={r.new} />
        <Num label="Tekrar (atlandı)" v={r.duplicates} />
        <Num label="Otomatik eşleşti" v={r.auto_matched} color="teal" />
        <Num label="Öneri" v={r.suggested} color="yellow.8" />
        <Num label="Eşleşmedi" v={r.unmatched} color="red" />
        <Num label="Kesim öncesi" v={r.before_cutoff} />
      </SimpleGrid>
      <Text size="sm" mt="sm">
        Gelen toplam: <MoneyText value={r.credit_total} fw={600} />
      </Text>
      {r.warnings.length + r.gaps.length > 0 && (
        <Alert color="orange" mt="sm">
          {[...r.warnings, ...r.gaps.map((g) => g.message)].map((w) => (
            <Text key={w} size="sm">
              {w}
            </Text>
          ))}
        </Alert>
      )}
      {r.suggested + r.unmatched > 0 && (
        <Button component={Link} to="/inceleme" mt="md">
          {r.suggested + r.unmatched} işlemi incele
        </Button>
      )}
    </Card>
  )
}

function Num({ label, v, color }: { label: string; v: number; color?: string }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fz={24} fw={700} c={color}>
        {v}
      </Text>
    </Stack>
  )
}

function Reconciliation({ siteId }: { siteId: number }) {
  const q = useQuery({
    queryKey: ['recon', siteId],
    queryFn: () =>
      api.get<{ available: boolean; cutoff: string; excel_total: string; system_total: string; unit_rows: { code: string; excel: string; system: string; diff: string }[]; rows: { code: string; period: string; excel: string; system: string; diff: string }[] }>(
        `/api/sites/${siteId}/reconciliation`,
      ),
  })
  const d = q.data
  if (!d) return null
  if (!d.available) return <Text c="dimmed">Takip Excel'i içe aktarılmadığı için mutabakat yok.</Text>
  return (
    <Stack>
      <Text size="sm">
        Kesim {periodLabel(d.cutoff)} sonrası: Excel'de <MoneyText value={d.excel_total} fw={600} />, sistemde <MoneyText value={d.system_total} fw={600} />. Ay
        etiketleri farklı olabilir (Excel'de açıklamadaki aya, sistemde gönderildiği aya yazılır); daire toplamlarına bakın.
      </Text>
      <Table striped fz="sm" maw={640}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Daire</Table.Th>
            <Table.Th className="num">Excel</Table.Th>
            <Table.Th className="num">Sistem</Table.Th>
            <Table.Th className="num">Fark</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {d.unit_rows.map((r) => (
            <Table.Tr key={r.code}>
              <Table.Td fw={600}>{r.code}</Table.Td>
              <Table.Td className="num"><MoneyText value={r.excel} /></Table.Td>
              <Table.Td className="num"><MoneyText value={r.system} /></Table.Td>
              <Table.Td className="num"><MoneyText value={r.diff} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {d.unit_rows.length === 0 && <Text c="teal">Daire toplamları birebir uyuşuyor.</Text>}
    </Stack>
  )
}
