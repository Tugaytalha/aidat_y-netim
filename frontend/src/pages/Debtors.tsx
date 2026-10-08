import { Badge, Button, SegmentedControl, Table, Text } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, download, type Debtor } from '../api'
import { ErrorAlert, Loading, MoneyText, NoSite, notifyError, PageHeader } from '../components/common'
import { UnitDrawer } from '../components/UnitDrawer'
import { useSite } from '../context'
import { periodLabel } from '../format'

const BUCKET_COLOR: Record<string, string> = { '1 ay': 'yellow', '2-3 ay': 'orange', '3+ ay': 'red' }

export default function Debtors() {
  const { siteId } = useSite()
  const [bucket, setBucket] = useState('borclu')
  const [open, setOpen] = useState<number | null>(null)
  const q = useQuery({ queryKey: ['debtors', siteId], queryFn: () => api.get<Debtor[]>(`/api/sites/${siteId}/debtors`), enabled: !!siteId })
  if (!siteId) return <NoSite />
  const rows = (q.data ?? []).filter((r) =>
    bucket === 'tum' ? true : bucket === 'borclu' ? r.overdue_months > 0 : bucket === 'avans' ? Number(r.balance) < 0 : r.bucket === bucket,
  )
  const total = rows.reduce((s, r) => s + Math.max(0, Number(r.balance)), 0)

  return (
    <>
      <PageHeader
        title="Borçlular"
        description="Bakiye = tahakkuklar − ödemeler. 'Geciken ay', ödemeler en eski borçtan başlanarak düşülünce kalan ödenmemiş ay sayısıdır."
        actions={
          <Button variant="default" leftSection={<IconDownload size={16} />}
            onClick={() => download(`/api/sites/${siteId}/export/debtors.xlsx`, 'borclular.xlsx').catch(notifyError)}>
            Excel
          </Button>
        }
      />
      <SegmentedControl
        mb="md"
        value={bucket}
        onChange={setBucket}
        data={[
          { value: 'borclu', label: 'Borçlu' },
          { value: '1 ay', label: '1 ay' },
          { value: '2-3 ay', label: '2-3 ay' },
          { value: '3+ ay', label: '3+ ay' },
          { value: 'avans', label: 'Avanslı' },
          { value: 'tum', label: 'Tümü' },
        ]}
      />
      <ErrorAlert error={q.error} />
      {q.isLoading ? (
        <Loading />
      ) : (
        <Table.ScrollContainer minWidth={700}>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Daire</Table.Th>
                <Table.Th>Sakin(ler)</Table.Th>
                <Table.Th className="num">Bakiye</Table.Th>
                <Table.Th>Geciken</Table.Th>
                <Table.Th>En eski ödenmemiş</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.unit_id} style={{ cursor: 'pointer' }} onClick={() => setOpen(r.unit_id)}>
                  <Table.Td fw={600}>{r.code}</Table.Td>
                  <Table.Td>{r.names.join(' / ')}</Table.Td>
                  <Table.Td className="num">
                    <MoneyText value={r.balance} colored fw={600} />
                  </Table.Td>
                  <Table.Td>
                    {r.overdue_months > 0 && (
                      <Badge color={BUCKET_COLOR[r.bucket] ?? 'gray'} variant="light">
                        {r.overdue_months} ay
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>{periodLabel(r.oldest_unpaid_period)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <Text mt="sm" size="sm" c="dimmed">
        {rows.length} daire · toplam alacak <MoneyText value={total} fw={600} />
      </Text>
      <UnitDrawer unitId={open} onClose={() => setOpen(null)} />
    </>
  )
}
