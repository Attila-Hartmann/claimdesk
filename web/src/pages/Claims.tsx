import { Alert, Badge, Button, FileButton, Group, Paper, SimpleGrid, Skeleton, Stack, Table, Text, Title, useMatches } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { api, type ClaimRow, DEMO } from '../api';
import { modelName, pct } from '../labels';

function Risk({ score }: { score: number | null }) {
  if (score == null) return <Text c="dimmed" size="sm">–</Text>;
  const color = score >= 0.5 ? 'var(--risk)' : score >= 0.2 ? '#d97706' : 'var(--ok)';
  return (
    <Group gap={8} wrap="nowrap" w={{ base: 92, sm: 130 }}>
      <div className="riskbar" style={{ flex: 1 }} aria-hidden>
        <span style={{ width: `${Math.max(4, score * 100)}%`, background: color }} />
      </div>
      <Text size="sm" fw={600} c={color} w={42} ta="right">{pct(score, 0)}</Text>
    </Group>
  );
}

const STATUS: Record<string, { label: string; color: string }> = {
  review: { label: 'Needs review', color: 'orange' },
  approved: { label: 'Approved', color: 'teal' },
  processing: { label: 'Processing', color: 'blue' },
  new: { label: 'New', color: 'gray' },
};

const MAX_BYTES = 4_000_000; // the API's limit: Lambda caps request bodies

function Upload() {
  const nav = useNavigate();
  const send = useMutation({
    mutationFn: (files: File[]) => {
      if (files.reduce((s, f) => s + f.size, 0) > MAX_BYTES) throw new Error('Up to 4 MB in total, please.');
      return api.upload(files);
    },
    onSuccess: (c) => nav(`/claims/${c.id}`),
  });
  return (
    <Paper withBorder p="md">
      <Group justify="space-between" gap="sm">
        <div style={{ flex: '1 1 320px' }}>
          <Text fw={600}>Try it with your own documents</Text>
          <Text size="sm" c="dimmed">
            Up to 5 PDFs or photos of a claim form, repair invoice or accident statement. Use blank or made-up documents, never real
            personal data. Your claim is visible only through its link and is deleted after 24 hours.
          </Text>
        </div>
        <FileButton onChange={(f) => f.length && send.mutate(f.slice(0, 5))} accept="application/pdf,image/png,image/jpeg" multiple>
          {(props) => <Button {...props} loading={send.isPending}>Upload documents</Button>}
        </FileButton>
      </Group>
      {send.isError && <Alert color="red" mt="sm">{send.error.message}</Alert>}
    </Paper>
  );
}

export function Claims() {
  const { data, isError, isPending } = useQuery({ queryKey: ['claims'], queryFn: api.claims });
  const nav = useNavigate();
  const rows = [...(data ?? [])].sort((a, b) => (b.fraud ?? 0) - (a.fraud ?? 0)); // handlers work the riskiest claims first
  const review = rows.filter((r) => r.status === 'review');
  const flagged = rows.filter((r) => (r.fraud ?? 0) >= 0.5);
  const spacing = useMatches({ base: 'xs', sm: 'md' });
  const wide = { visibleFrom: 'sm' } as const; // phones keep claim, issues and risk; status moves under the claim id

  return (
    <Stack gap="lg">
      <div>
        <Title order={1}>Motor claims</Title>
        <Text c="dimmed" maw={760} mt={6}>
          Each claim arrives as scanned or digital documents. The pipeline reads them, routes each page to the right extractor, checks
          the numbers with deterministic rules and scores fraud risk. A handler reviews every claim; their corrections train the next
          model version.
        </Text>
      </div>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        {[
          ['Claims', rows.length],
          ['Waiting for review', review.length],
          ['High fraud risk', flagged.length],
          ['Rule violations', rows.reduce((s, r) => s + r.issues, 0)],
        ].map(([label, n]) => (
          <Paper key={label} p="md" withBorder>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
            {isPending ? <Skeleton height={28} width={48} mt={4} /> : <Text size="xl" fw={700}>{n}</Text>}
          </Paper>
        ))}
      </SimpleGrid>
      {!DEMO && <Upload />}
      {isError && <Alert color="red">The API is not reachable.</Alert>}
      <Paper withBorder>
        <Table highlightOnHover verticalSpacing="sm" horizontalSpacing={spacing}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Claim</Table.Th>
              <Table.Th {...wide}>Status</Table.Th>
              <Table.Th {...wide}>Documents</Table.Th>
              <Table.Th {...wide}>Extracted by</Table.Th>
              <Table.Th>Rule issues</Table.Th>
              <Table.Th>Fraud risk</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isPending && Array.from({ length: 6 }, (_, i) => (
              <Table.Tr key={`s${i}`}>{Array.from({ length: 6 }, (_, j) => <Table.Td key={j} visibleFrom={j && j < 4 ? 'sm' : undefined}><Skeleton height={14} radius="sm" /></Table.Td>)}</Table.Tr>
            ))}
            {rows.map((r: ClaimRow) => (
              <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/claims/${r.id}`)}>
                <Table.Td>
                  <Text fw={600} className="mono" size="sm">{r.ref ?? r.id}</Text>
                  <Text size="xs" c="dimmed">{r.received_at.slice(0, 10)}</Text>
                  <Badge hiddenFrom="sm" mt={4} size="sm" variant="light" color={STATUS[r.status]?.color}>{STATUS[r.status]?.label ?? r.status}</Badge>
                </Table.Td>
                <Table.Td {...wide}><Badge variant="light" color={STATUS[r.status]?.color}>{STATUS[r.status]?.label ?? r.status}</Badge></Table.Td>
                <Table.Td {...wide}>{r.docs}</Table.Td>
                <Table.Td {...wide}>
                  <Group gap={4}>
                    {r.models.map((m) => (
                      <Badge key={m} variant={m.startsWith('claimdesk-') ? 'filled' : 'outline'} color={m.startsWith('claimdesk-') ? 'violet' : 'gray'}>
                        {modelName(m)}
                      </Badge>
                    ))}
                  </Group>
                </Table.Td>
                <Table.Td>{r.issues ? <Badge color="red" variant="light">{r.issues}</Badge> : <Text c="dimmed" size="sm">none</Text>}</Table.Td>
                <Table.Td><Risk score={r.fraud} /></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
    </Stack>
  );
}
