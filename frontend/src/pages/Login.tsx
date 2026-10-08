import { Button, Center, Paper, PasswordInput, Stack, Text, TextInput, ThemeIcon, Title } from '@mantine/core'
import { IconCalculator } from '@tabler/icons-react'
import { useState, type FormEvent } from 'react'
import { ErrorAlert } from '../components/common'
import { useAuth } from '../context'

export default function Login() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" w="100%" maw={380}>
        <form onSubmit={submit}>
          <Stack>
            <Stack gap={6} align="center">
              <ThemeIcon size={48} variant="light">
                <IconCalculator size={28} />
              </ThemeIcon>
              <Title order={3}>Ortabahçe Aidat</Title>
              <Text c="dimmed" size="sm">
                Yönetim paneline giriş
              </Text>
            </Stack>
            <ErrorAlert error={error} />
            <TextInput label="E-posta" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required autoComplete="username" />
            <PasswordInput
              label="Şifre"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              required
              autoComplete="current-password"
            />
            <Button type="submit" loading={busy} fullWidth>
              Giriş yap
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  )
}
