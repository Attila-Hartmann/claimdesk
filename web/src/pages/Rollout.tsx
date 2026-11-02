import { Alert, Badge, Button, Group, Paper, Select, SimpleGrid, Slider, Stack, Table, Text, Timeline, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, DEMO, type EvalSummary } from '../api';
import { modelName, pct, usd } from '../labels';

const GROUPS: [string, string][] = [
  ['pdf_text', 'Digital PDFs'], ['ocr', 'Scans (OCR)'], ['claim_form', 'Claim forms'], ['repair_invoice', 'Invoices'], ['accident_statement', 'Accident statements'],
];

function EvalTable({ evals }: { evals: Record<string, EvalSummary> }) {
  const rows = Object.values(evals).sort((a, b) => (a.endpoint === 'champion' ? -1 : b.endpoint === 'champion' ? 1 : a.model.localeCompare(b.model)));
  const best = Math.max(...rows.map((r) => r.field_accuracy));
  return (
    <Table striped verticalSpacing="sm" fz="sm">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Model</Table.Th>
          <Table.Th ta="right">Fields correct</Table.Th>
          <Table.Th ta="right">Documents fully correct</Table.Th>
          {GROUPS.map(([k, l]) => <Table.Th key={k} ta="right">{l}</Table.Th>)}
          <Table.Th ta="right">Input tokens / doc</Table.Th>
          <Table.Th ta="right">Cost / 1,000 docs</Table.Th>
          <Table.Th ta="right">Median latency</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((r) => (
          <Table.Tr key={r.model}>
            <Table.Td>
              <Text fw={600} size="sm">{modelName(r.endpoint === 'champion' ? 'champion' : r.model)}</Text>
              <Text size="xs" c="dimmed" className="mono">{r.model}</Text>
            </Table.Td>
            <Table.Td ta="right" fw={r.field_accuracy === best ? 700 : 400}>{pct(r.field_accuracy)}</Table.Td>
            <Table.Td ta="right">{pct(r.doc_exact)}</Table.Td>
            {GROUPS.map(([k]) => <Table.Td key={k} ta="right">{pct(r.by_group[k])}</Table.Td>)}
            <Table.Td ta="right">{Math.round(r.tokens_in_avg)}</Table.Td>
            <Table.Td ta="right">{usd(r.gpu_cost_per_1k_docs_usd ?? r.cost_per_1k_docs_usd)}{r.gpu_cost_per_1k_docs_usd != null && <Text span size="xs" c="dimmed"> GPU</Text>}</Table.Td>
            <Table.Td ta="right">{r.p50_ms ? `${(r.p50_ms / 1000).toFixed(1)} s` : '–'}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function Rollout() {
  const qc = useQueryClient();
  const { data: ro } = useQuery({ queryKey: ['rollout'], queryFn: api.rollout });
  const { data: evals } = useQuery({ queryKey: ['evals'], queryFn: api.evals });
  const [challenger, setChallenger] = useState<string | null>(null);
  const [share, setShare] = useState(20);
  const apply = useMutation({ mutationFn: () => api.setCanary(challenger, share), onSuccess: () => qc.invalidateQueries({ queryKey: ['rollout'] }) });
  const versions = Object.values(evals ?? {}).map((e) => e.model).filter((m) => m.startsWith('claimdesk-'));
  const s = ro?.state;
  const color = { promote: 'teal', rollback: 'red', wait: 'blue', none: 'gray' }[ro?.decision.action ?? 'none'];

  return (
    <Stack gap="lg">
      <div>
        <Title order={1}>Model rollout</Title>
        <Text c="dimmed" maw={820} mt={6}>
          A fine-tuned open-weight model replaces the frontier API only if it earns it. Offline: it must match the champion on held-out
          documents. Online: it takes a small share of real traffic, every handler review scores it field by field, and a statistical test
          promotes it or rolls it back.
        </Text>
      </div>

      <Paper withBorder p="md">
        <Title order={3} mb="sm">Offline evaluation on held-out documents</Title>
        {evals ? <EvalTable evals={evals} /> : <Text c="dimmed">No eval reports yet.</Text>}
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {s && [s.champion, s.challenger].filter(Boolean).map((m, i) => {
          const st = ro?.stats[m as string];
          return (
            <Paper key={m} withBorder p="md">
              <Group justify="space-between">
                <Text fw={700}>{modelName(m)}</Text>
                <Badge variant="light" color={i === 0 ? 'gray' : 'violet'}>{i === 0 ? 'champion' : `canary ${s.canary_pct}%`}</Badge>
              </Group>
              <SimpleGrid cols={3} mt="sm">
                <div><Text size="xs" c="dimmed">Fields accepted by handlers</Text><Text fw={700} size="lg">{pct(st?.acceptance)}</Text></div>
                <div><Text size="xs" c="dimmed">Reviewed documents</Text><Text fw={700} size="lg">{st?.docs ?? 0}</Text></div>
                <div><Text size="xs" c="dimmed">Average latency</Text><Text fw={700} size="lg">{st?.avg_latency_ms ? `${(st.avg_latency_ms / 1000).toFixed(1)} s` : '–'}</Text></div>
              </SimpleGrid>
            </Paper>
          );
        })}
      </SimpleGrid>

      {ro && (
        <Alert color={color} title={`Decision: ${ro.decision.action}`}>
          {ro.decision.reason}. Promotion needs the challenger to be no worse than the champion on at least 900 reviewed fields; a
          significantly lower acceptance rate (z &lt; −2) rolls it back automatically.
        </Alert>
      )}

      {!DEMO && (
        <Paper withBorder p="md">
          <Title order={4} mb="sm">Start a canary</Title>
          <Group align="flex-end">
            <Select label="Challenger" data={versions} value={challenger} onChange={setChallenger} placeholder="choose a version" w={220} />
            <div style={{ width: 260 }}>
              <Text size="sm" mb={4}>Traffic share: {share}%</Text>
              <Slider min={5} max={50} step={5} value={share} onChange={setShare} />
            </div>
            <Button onClick={() => apply.mutate()} disabled={!challenger} loading={apply.isPending}>Apply</Button>
          </Group>
        </Paper>
      )}

      <Paper withBorder p="md">
        <Title order={4} mb="md">History</Title>
        <Timeline bulletSize={14} lineWidth={2} active={(s?.history.length ?? 0) - 1}>
          {[...(s?.history ?? [])].reverse().map((h, i) => (
            <Timeline.Item key={i} title={`${h.action}${h.challenger ? ` · ${modelName(h.challenger)}` : ''}${h.pct ? ` at ${h.pct}%` : ''}${h.auto ? ' (automatic)' : ''}`}>
              <Text size="sm" c="dimmed">{h.reason}</Text>
              <Text size="xs" c="dimmed">{h.at.replace('T', ' ')}</Text>
            </Timeline.Item>
          ))}
        </Timeline>
      </Paper>
    </Stack>
  );
}
