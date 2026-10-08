import { AppShell, Badge, Burger, Group, NavLink, ScrollArea, Select, Text, ThemeIcon, UnstyledButton } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBuildingCommunity, IconCalculator, IconChecklist, IconFileImport, IconHome, IconLayoutGrid, IconListDetails,
  IconLogout, IconReceipt2, IconScale, IconSettings, IconUsers, IconAlertCircle,
} from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Navigate, NavLink as RouterLink, Route, Routes, useLocation } from 'react-router-dom'
import { api, type Dashboard as DashboardData } from './api'
import { Loading } from './components/common'
import { useAuth, useSite } from './context'
import Dashboard from './pages/Dashboard'
import Debtors from './pages/Debtors'
import Grid from './pages/Grid'
import Imports from './pages/Imports'
import Ledger from './pages/Ledger'
import Login from './pages/Login'
import Opening from './pages/Opening'
import Review from './pages/Review'
import Settings from './pages/Settings'
import Sites from './pages/Sites'
import Transactions from './pages/Transactions'
import Units from './pages/Units'

const NAV: { to: string; label: string; icon: ReactNode; badge?: 'review' }[] = [
  { to: '/', label: 'Pano', icon: <IconHome size={18} /> },
  { to: '/inceleme', label: 'İnceleme kuyruğu', icon: <IconChecklist size={18} />, badge: 'review' },
  { to: '/cizelge', label: 'Tahsilat çizelgesi', icon: <IconLayoutGrid size={18} /> },
  { to: '/daireler', label: 'Daireler', icon: <IconBuildingCommunity size={18} /> },
  { to: '/borclular', label: 'Borçlular', icon: <IconAlertCircle size={18} /> },
  { to: '/islemler', label: 'İşlemler', icon: <IconListDetails size={18} /> },
  { to: '/ice-aktar', label: 'Ekstre yükle', icon: <IconFileImport size={18} /> },
  { to: '/tahakkuk', label: 'Tarife ve tahakkuk', icon: <IconReceipt2 size={18} /> },
  { to: '/acilis', label: 'Açılış bakiyesi', icon: <IconScale size={18} /> },
  { to: '/ayarlar', label: 'Site ayarları', icon: <IconSettings size={18} /> },
]

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (!user) return <Login />
  return <Shell />
}

function Shell() {
  const [opened, { toggle, close }] = useDisclosure()
  const { user, logout } = useAuth()
  const { sites, siteId, setSiteId } = useSite()
  const location = useLocation()
  const dash = useQuery({
    queryKey: ['dashboard', siteId, 'nav'],
    queryFn: () => api.get<DashboardData>(`/api/sites/${siteId}/dashboard`),
    enabled: !!siteId,
    staleTime: 30_000,
  })
  const review = dash.data?.needs_review ?? 0

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 250, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <ThemeIcon variant="light" size="lg">
              <IconCalculator size={20} />
            </ThemeIcon>
            <Text fw={700} visibleFrom="xs">
              Ortabahçe Aidat
            </Text>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Select
              aria-label="Site"
              placeholder="Site seçin"
              data={sites.map((s) => ({ value: String(s.id), label: s.name }))}
              value={siteId ? String(siteId) : null}
              onChange={(v) => setSiteId(v ? Number(v) : null)}
              w={{ base: 170, sm: 280 }}
              allowDeselect={false}
            />
            <UnstyledButton onClick={logout} title="Çıkış">
              <Group gap={6} wrap="nowrap">
                <Text size="sm" c="dimmed" visibleFrom="md">
                  {user?.full_name || user?.email}
                </Text>
                <IconLogout size={18} />
              </Group>
            </UnstyledButton>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        <AppShell.Section grow component={ScrollArea}>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              component={RouterLink}
              to={n.to}
              label={n.label}
              leftSection={n.icon}
              active={n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)}
              onClick={close}
              rightSection={n.badge === 'review' && review > 0 ? <Badge size="sm" color="yellow">{review}</Badge> : undefined}
            />
          ))}
        </AppShell.Section>
        <AppShell.Section>
          <NavLink
            component={RouterLink}
            to="/siteler"
            label="Siteler"
            leftSection={<IconUsers size={18} />}
            active={location.pathname.startsWith('/siteler')}
            onClick={close}
          />
        </AppShell.Section>
      </AppShell.Navbar>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/inceleme" element={<Review />} />
          <Route path="/cizelge" element={<Grid />} />
          <Route path="/daireler" element={<Units />} />
          <Route path="/borclular" element={<Debtors />} />
          <Route path="/islemler" element={<Transactions />} />
          <Route path="/ice-aktar" element={<Imports />} />
          <Route path="/tahakkuk" element={<Ledger />} />
          <Route path="/acilis" element={<Opening />} />
          <Route path="/ayarlar" element={<Settings />} />
          <Route path="/siteler" element={<Sites />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  )
}
