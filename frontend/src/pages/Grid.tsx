import { Button, Group, Select, Text } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { api, download, type GridData } from '../api'
import { ErrorAlert, Loading, MoneyText, NoSite, notifyError, PageHeader } from '../components/common'
import { UnitDrawer } from '../components/UnitDrawer'
import { useSite } from '../context'
import { addMonths, currentPeriod, money, moneyShort, periodLabel, periodOptions } from '../format'

export default function Grid() {
  const { siteId } = useSite()
  const [end, setEnd] = useState(currentPeriod())
  const [start, setStart] = useState(addMonths(currentPeriod(), -11))
  const [open, setOpen] = useState<{ unit: number; period: string | null } | null>(null)
  const q = useQuery({
    queryKey: ['grid', siteId, start, end],
    queryFn: () => api.get<GridData>(`/api/sites/${siteId}/grid`, { start, end }),
    enabled: !!siteId,
  })
  if (!siteId) return <NoSite />
  const opts = periodOptions(addMonths(currentPeriod(), -60), addMonths(currentPeriod(), 12))
  const g = q.data

  return (
    <>
      <PageHeader
        title="Tahsilat çizelgesi"
        description="Her hücre o ay gönderilen ödemelerin toplamıdır. Renk o ayın tahakkukuna göre: yeşil ödendi, sarı eksik, kırmızı ödenmedi. Hücreye tıklayınca dairenin ekstresi açılır."
        actions={
          <>
            <Select w={150} data={opts} value={start} onChange={(v) => v && setStart(v)} allowDeselect={false} aria-label="Başlangıç" />
            <Select w={150} data={opts} value={end} onChange={(v) => v && setEnd(v)} allowDeselect={false} aria-label="Bitiş" />
            <Button
              variant="default"
              leftSection={<IconDownload size={16} />}
              onClick={() => download(`/api/sites/${siteId}/export/grid.xlsx?start=${start}&end=${end}`, 'tahsilat.xlsx').catch(notifyError)}
            >
              Excel
            </Button>
          </>
        }
      />
      <ErrorAlert error={q.error} />
      {q.isLoading && <Loading />}
      {g && (
        <div className="grid-wrap">
          <table className="grid-table">
            <thead>
              <tr>
                <th className="sticky-col">Daire</th>
                {g.periods.map((p) => (
                  <th key={p}>{periodLabel(p, true)}</th>
                ))}
                <th>Bakiye</th>
              </tr>
            </thead>
            <tbody>
              {g.blocks.map((b) => (
                <Fragment key={b.name}>
                  <tr className="block-row">
                    <td className="sticky-col">{b.name} blok</td>
                    <td colSpan={g.periods.length + 1} />
                  </tr>
                  {b.units.map((u) => (
                    <tr key={u.unit_id}>
                      <td className="sticky-col cell-click" onClick={() => setOpen({ unit: u.unit_id, period: null })}>
                        <Text size="sm" fw={600} span>
                          {u.code}
                        </Text>{' '}
                        <Text size="xs" c="dimmed" span>
                          {u.names.join(' / ')}
                        </Text>
                      </td>
                      {g.periods.map((p) => {
                        const c = u.cells[p]
                        const cls = c ? `num cell-click cell-${c.status}` : 'num'
                        const title = c ? `Ödenen ${money(c.paid)} · Tahakkuk ${money(c.charged)}` : undefined
                        return (
                          <td key={p} className={cls} title={title} onClick={c ? () => setOpen({ unit: u.unit_id, period: p }) : undefined}>
                            {c ? moneyShort(c.paid) || '—' : ''}
                          </td>
                        )
                      })}
                      <td className="num">
                        <MoneyText value={u.balance} colored fw={600} />
                      </td>
                    </tr>
                  ))}
                </Fragment>
              ))}
              <tr className="block-row">
                <td className="sticky-col">Toplam tahsilat</td>
                {g.periods.map((p) => (
                  <td key={p} className="num">
                    {moneyShort(g.totals[p])}
                  </td>
                ))}
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <Group mt="xs" gap="lg">
        <Text size="xs" c="dimmed">
          <span className="cell-paid" style={{ padding: '0 8px', marginRight: 4 }} /> ödendi
        </Text>
        <Text size="xs" c="dimmed">
          <span className="cell-partial" style={{ padding: '0 8px', marginRight: 4 }} /> eksik
        </Text>
        <Text size="xs" c="dimmed">
          <span className="cell-unpaid" style={{ padding: '0 8px', marginRight: 4 }} /> ödenmedi
        </Text>
      </Group>
      <UnitDrawer unitId={open?.unit ?? null} focusPeriod={open?.period} onClose={() => setOpen(null)} />
    </>
  )
}
