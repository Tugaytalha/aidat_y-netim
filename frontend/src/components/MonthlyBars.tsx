import { Box, Group, Text, Tooltip, VisuallyHidden } from '@mantine/core'
import { money, moneyShort, num, periodLabel } from '../format'

/** Tek seri (aylık tahsilat) çubuk grafik. Renk doğrulandı: açık #099268, koyu #0ca678. */
export function MonthlyBars({ data, height = 160 }: { data: { period: string; collected: string }[]; height?: number }) {
  const max = Math.max(1, ...data.map((d) => num(d.collected)))
  const last = data[data.length - 1]
  return (
    <Box>
      <Group align="flex-end" gap={2} h={height} wrap="nowrap" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
        {data.map((d) => {
          const v = num(d.collected)
          const h = v > 0 ? Math.max(3, (v / max) * (height - 20)) : 0
          return (
            <Tooltip key={d.period} label={`${periodLabel(d.period)}: ${money(v)}`} withArrow>
              {/* Hedef alan çubuktan büyük: tüm sütun yüksekliği */}
              <Box style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', cursor: 'default' }}>
                {d === last && v > 0 && (
                  <Text size="xs" ta="center" c="dimmed" mb={2} className="num" style={{ textAlign: 'center' }}>
                    {moneyShort(v)}
                  </Text>
                )}
                <Box
                  style={{
                    height: h,
                    background: 'light-dark(#099268, #0ca678)',
                    borderRadius: '4px 4px 0 0',
                    margin: '0 1px',
                  }}
                />
              </Box>
            </Tooltip>
          )
        })}
      </Group>
      <Group gap={2} wrap="nowrap" mt={4}>
        {data.map((d) => (
          <Text key={d.period} size="10px" c="dimmed" ta="center" style={{ flex: 1 }}>
            {periodLabel(d.period, true).split(' ')[0]}
          </Text>
        ))}
      </Group>
      <VisuallyHidden>
        <table>
          <caption>Aylık tahsilat</caption>
          <tbody>
            {data.map((d) => (
              <tr key={d.period}>
                <th>{periodLabel(d.period)}</th>
                <td>{money(d.collected)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </VisuallyHidden>
    </Box>
  )
}
