import { Alert, Badge, Group, Loader, Select, Stack, Text, Title, type SelectProps } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, ApiError, type Money, type UnitRow } from '../api'
import { useSite } from '../context'
import { money, num, STATUS_LABELS } from '../format'

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <Group justify="space-between" align="flex-end" mb="lg" wrap="wrap" gap="sm">
      <Stack gap={4}>
        <Title order={2}>{title}</Title>
        {description && (
          <Text c="dimmed" size="sm" maw={720}>
            {description}
          </Text>
        )}
      </Stack>
      {actions && <Group gap="xs">{actions}</Group>}
    </Group>
  )
}

export function MoneyText({ value, colored = false, fw }: { value: Money | null | undefined; colored?: boolean; fw?: number }) {
  const n = num(value)
  const color = colored ? (n > 0 ? 'red.7' : n < 0 ? 'teal.7' : 'dimmed') : undefined
  return (
    <Text span className="num" c={color} fw={fw} inherit>
      {money(value)}
    </Text>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_LABELS[status] ?? { label: status, color: 'gray' }
  return (
    <Badge color={s.color} variant="light">
      {s.label}
    </Badge>
  )
}

export function Loading() {
  return (
    <Group justify="center" p="xl">
      <Loader />
    </Group>
  )
}

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <Alert color="red" icon={<IconAlertTriangle size={18} />} mb="md">
      {error instanceof Error ? error.message : String(error)}
    </Alert>
  )
}

export function NoSite() {
  return (
    <Alert color="blue" title="Site seçilmedi">
      Başlamak için soldaki menüden <b>Siteler</b> sayfasına gidip bir site oluşturun ya da takip Excel'inden içe aktarın.
    </Alert>
  )
}

export function notifyError(e: unknown) {
  notifications.show({ color: 'red', title: 'Hata', message: e instanceof ApiError || e instanceof Error ? e.message : String(e) })
}

export function notifyOk(message: string, title = 'Tamam') {
  notifications.show({ color: 'teal', title, message })
}

export function useUnits() {
  const { siteId } = useSite()
  return useQuery({
    queryKey: ['units', siteId],
    queryFn: () => api.get<UnitRow[]>(`/api/sites/${siteId}/units`),
    enabled: !!siteId,
  })
}

export function UnitSelect(props: Omit<SelectProps, 'data'> & { value: string | null; onChange: (v: string | null) => void }) {
  const units = useUnits()
  const data = (units.data ?? []).map((u) => ({
    value: String(u.id),
    label: `${u.code}${u.people.length ? ' · ' + u.people.map((p) => p.name).join(' / ') : ''}`,
  }))
  return <Select searchable placeholder="Daire seçin" nothingFoundMessage="Bulunamadı" data={data} {...props} />
}
