import { Alert, Button, Card, Group, List, Select, SimpleGrid, Stack, Text, Title } from '@mantine/core'
import { IconAlertTriangle, IconChecklist, IconFileImport } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Dashboard as DashboardData } from '../api'
import { ErrorAlert, Loading, NoSite, PageHeader } from '../components/common'
import { MonthlyBars } from '../components/MonthlyBars'
import { useSite } from '../context'
import { addMonths, currentPeriod, dateTR, money, periodLabel, periodOptions } from '../format'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card withBorder padding="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text fz={26} fw={700} className="num" style={{ textAlign: 'left' }}>
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Card>
  )
}

export default function Dashboard() {
  const { siteId, site } = useSite()
  const [period, setPeriod] = useState(currentPeriod())
  const q = useQuery({
    queryKey: ['dashboard', siteId, period],
    queryFn: () => api.get<DashboardData>(`/api/sites/${siteId}/dashboard`, { period }),
    enabled: !!siteId,
  })
  if (!siteId) return <NoSite />
  if (q.isLoading) return <Loading />
  const d = q.data
  return (
    <>
      <PageHeader
        title={site?.name ?? 'Pano'}
        description={d?.last_transaction_date ? `Son banka hareketi: ${dateTR(d.last_transaction_date)}` : 'Henüz banka ekstresi yüklenmedi.'}
        actions={
          <Select
            w={170}
            data={periodOptions(addMonths(currentPeriod(), -24), currentPeriod())}
            value={period}
            onChange={(v) => v && setPeriod(v)}
            allowDeselect={false}
            aria-label="Dönem"
          />
        }
      />
      <ErrorAlert error={q.error} />
      {d && (
        <Stack>
          {d.needs_review > 0 && (
            <Alert color="yellow" icon={<IconChecklist size={18} />} title={`${d.needs_review} ödeme incelemeyi bekliyor`}>
              <Button component={Link} to="/inceleme" size="xs" variant="light" color="yellow" mt={4}>
                İnceleme kuyruğuna git
              </Button>
            </Alert>
          )}
          {d.gaps.length > 0 && (
            <Alert color="orange" icon={<IconAlertTriangle size={18} />} title="Ekstrelerde boşluk olabilir">
              <List size="sm">
                {d.gaps.map((g) => (
                  <List.Item key={g.after + g.before}>{g.message}</List.Item>
                ))}
              </List>
            </Alert>
          )}
          <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
            <Stat
              label={`${periodLabel(period)} tahsilat oranı`}
              value={d.collection_rate === null ? '—' : `%${Math.round(d.collection_rate * 100)}`}
              hint={`${money(d.collected_this_month)} / ${money(d.charged_this_month)} tahakkuk`}
            />
            <Stat label="Toplam alacak" value={money(d.total_receivable)} hint={`${d.debtor_units} / ${d.unit_count} daire geciken ödemeli`} />
            <Stat label="Avans (fazla ödeme)" value={money(d.total_advance)} hint="Dairelerin ileriye dönük bakiyesi" />
            <Stat
              label="Banka işlemleri"
              value={String((d.transactions.matched ?? 0) + (d.transactions.suggested ?? 0) + (d.transactions.unmatched ?? 0) + (d.transactions.ignored ?? 0))}
              hint={`${d.transactions.matched ?? 0} eşleşti · ${d.needs_review} bekliyor · ${d.transactions.ignored ?? 0} yok sayıldı`}
            />
          </SimpleGrid>
          <Card withBorder padding="lg">
            <Group justify="space-between" mb="sm">
              <Title order={4}>Aylık tahsilat</Title>
              <Text size="xs" c="dimmed">
                Son 12 ay · ödemeler gönderildiği aya yazılır
              </Text>
            </Group>
            <MonthlyBars data={d.monthly} />
          </Card>
          <Card withBorder padding="md">
            <Group justify="space-between">
              <Text size="sm">
                {d.last_import ? (
                  <>
                    Son içe aktarım: <b>{d.last_import.file_name}</b> ({dateTR(d.last_import.at)})
                  </>
                ) : (
                  'Henüz içe aktarım yok.'
                )}
              </Text>
              <Button component={Link} to="/ice-aktar" size="xs" leftSection={<IconFileImport size={14} />}>
                Ekstre yükle
              </Button>
            </Group>
          </Card>
        </Stack>
      )}
    </>
  )
}
