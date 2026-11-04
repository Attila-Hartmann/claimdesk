import { Accordion, Alert, Anchor, Badge, Box, Button, Code, Grid, Group, Paper, Stack, Switch, Table, Tabs, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';

import { api, type Doc, type Issue, useReadonly } from '../api';
import { DOC_TYPE, FIELD, modelName, pct, usd } from '../labels';

type Fields = Record<string, unknown>;

function issueFor(issues: Issue[], key: string) {
  return issues.find((i) => i.field === key || i.field.startsWith(`${key}[`));
}

/** Generic editor over the extraction schema: scalars, nested objects, string lists and line-item tables. */
function FieldEditor({ value, onChange, issues, readOnly }: { value: Fields; onChange: (v: Fields) => void; issues: Issue[]; readOnly: boolean }) {
  const set = (k: string, v: unknown) => onChange({ ...value, [k]: v });
  return (
    <Stack gap="xs">
      {Object.entries(value).map(([k, v]) => {
        const issue = issueFor(issues, k);
        const label = FIELD[k] ?? k;
        if (typeof v === 'boolean') {
          return <Switch key={k} label={label} checked={v} disabled={readOnly} onChange={(e) => set(k, e.currentTarget.checked)} />;
        }
        if (Array.isArray(v) && v.length && typeof v[0] === 'object') {
          const rows = v as Fields[];
          const cols = Object.keys(rows[0]);
          return (
            <div key={k}>
              <Text size="sm" fw={500} mb={4}>{label}</Text>
              <Table.ScrollContainer minWidth={420} type="native">
              <Table withTableBorder withColumnBorders fz="xs">
                <Table.Thead><Table.Tr>{cols.map((c) => <Table.Th key={c}>{FIELD[c] ?? c.replaceAll('_', ' ')}</Table.Th>)}</Table.Tr></Table.Thead>
                <Table.Tbody>
                  {rows.map((row, i) => (
                    <Table.Tr key={i} className={issues.some((x) => x.field === `${k}[${i}]`) ? 'field-issue' : undefined}>
                      {cols.map((c) => (
                        <Table.Td key={c} p={2}>
                          <TextInput size="xs" variant="unstyled" classNames={{ input: 'mono' }} readOnly={readOnly} value={String(row[c] ?? '')}
                            aria-label={`${label} ${i + 1} ${c}`}
                            onChange={(e) => set(k, rows.map((r, j) => (j === i ? { ...r, [c]: typeof r[c] === 'number' ? Number(e.currentTarget.value) : e.currentTarget.value } : r)))} />
                        </Table.Td>
                      ))}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
              </Table.ScrollContainer>
            </div>
          );
        }
        if (v && typeof v === 'object' && !Array.isArray(v)) {
          return (
            <Paper key={k} p="xs" withBorder bg="var(--mist)">
              <Text size="sm" fw={500} mb={4}>{label}</Text>
              <FieldEditor value={v as Fields} onChange={(nv) => set(k, nv)} issues={[]} readOnly={readOnly} />
            </Paper>
          );
        }
        const isList = Array.isArray(v);
        return (
          <TextInput key={k} label={label} className={issue ? 'field-issue' : undefined} classNames={{ input: 'mono' }} readOnly={readOnly} error={issue?.message}
            value={isList ? (v as string[]).join('; ') : String(v ?? '')}
            onChange={(e) => {
              const t = e.currentTarget.value;
              set(k, isList ? t.split(';').map((s) => s.trim()).filter(Boolean) : typeof v === 'number' ? Number(t.replace(/\s/g, '')) : t);
            }} />
        );
      })}
    </Stack>
  );
}

function DocumentPanel({ cid, doc }: { cid: string; doc: Doc }) {
  const qc = useQueryClient();
  const readonly = useReadonly();
  const [fields, setFields] = useState<Fields>(doc.review?.fields ?? doc.fields ?? {});
  useEffect(() => setFields(doc.review?.fields ?? doc.fields ?? {}), [doc]);
  const approve = useMutation({
    mutationFn: () => api.review(cid, doc.doc_id, fields),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['claim', cid] }),
  });
  const url = api.fileUrl(doc.file);
  const fine = doc.model?.startsWith('claimdesk-');

  return (
    <Grid gap="lg">
      <Grid.Col span={{ base: 12, md: 6 }}>
        <div className="doc-frame">
          {doc.file.endsWith('.pdf') ? (
            <>
              <Box visibleFrom="md"><iframe src={`${url}#toolbar=0&navpanes=0&view=FitH`} title={doc.name} /></Box>
              {/* mobile browsers don't render PDFs inside iframes */}
              <Button hiddenFrom="md" component="a" href={url} target="_blank" rel="noopener" variant="light" fullWidth radius={0}>Open the PDF</Button>
            </>
          ) : <img src={url} alt={`Scan of ${doc.name}`} />}
        </div>
        <Accordion mt="sm" variant="contained">
          <Accordion.Item value="text">
            <Accordion.Control>
              What the model read ({doc.text_method === 'ocr' ? `OCR of a scan, ${doc.ocr_ms} ms` : 'PDF text layer'})
            </Accordion.Control>
            <Accordion.Panel><Code block fz="xs">{doc.text}</Code></Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 6 }}>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap={6}>
              <Badge variant="light">{doc.type ? DOC_TYPE[doc.type] : '?'}</Badge>
              <Text size="xs" c="dimmed">classifier {pct(doc.type_confidence, 0)}</Text>
            </Group>
            <Group gap={6}>
              <Badge color={fine ? 'violet' : 'gray'} variant={fine ? 'filled' : 'outline'}>{modelName(doc.model)}</Badge>
              <Text size="xs" c="dimmed">{doc.latency_ms} ms · {doc.tokens_in}→{doc.tokens_out} tokens{doc.cost_usd ? ` · ${usd(doc.cost_usd, 5)}` : ''}</Text>
            </Group>
          </Group>
          {doc.error && <Alert color="red" title="The model returned invalid output">{doc.error}</Alert>}
          {!!doc.issues?.length && (
            <Alert color="orange" title="Rule checks">
              {doc.issues.map((i) => <Text key={i.code + i.field} size="sm">{i.message}</Text>)}
            </Alert>
          )}
          <FieldEditor value={fields} onChange={setFields} issues={doc.issues ?? []} readOnly={!!doc.review || readonly} />
          {doc.review ? (
            <Alert color="teal" title={`Reviewed${doc.review.simulated ? ' (simulated reviewer)' : ''}`}>
              {doc.review.accepted} of {doc.review.total} fields accepted as extracted.
              {doc.review.corrected.length > 0 && <> Corrected: {doc.review.corrected.map((c) => FIELD[c.split('.')[0]] ?? c).join(', ')}.</>}
            </Alert>
          ) : (
            <Group>
              <Button onClick={() => approve.mutate()} loading={approve.isPending} disabled={readonly}>Approve fields</Button>
              {readonly && <Text size="sm" c="dimmed">Reviews are off on the public demo, so visitors cannot skew the rollout statistics.</Text>}
            </Group>
          )}
        </Stack>
      </Grid.Col>
    </Grid>
  );
}

export function ClaimDetail() {
  const { id = '' } = useParams();
  const { data: c, isError } = useQuery({ queryKey: ['claim', id], queryFn: () => api.claim(id) });
  if (isError) return <Alert color="red">Claim not found.</Alert>;
  if (!c) return <Text c="dimmed">Loading…</Text>;
  const fraud = c.fraud?.score;

  return (
    <Stack gap="lg">
      <Anchor component={Link} to="/" size="sm">Back to claims</Anchor>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={1} className="mono">{c.ref ?? c.id}</Title>
          <Text c="dimmed" size="sm">{c.documents.length} documents · received {c.received_at.slice(0, 16).replace('T', ' ')}</Text>
        </div>
        <Paper p="md" withBorder miw={320}>
          <Group justify="space-between">
            <Text fw={600}>Fraud risk</Text>
            <Text fw={700} size="xl" c={fraud == null ? 'dimmed' : fraud >= 0.5 ? 'var(--risk)' : fraud >= 0.2 ? '#d97706' : 'var(--ok)'}>
              {pct(fraud, 0)}
            </Text>
          </Group>
          <Stack gap={4} mt={6}>
            {(c.fraud?.reasons ?? []).map((r) => (
              <Group key={r.feature} justify="space-between" wrap="nowrap" gap="sm">
                <Text size="xs">{r.label} <Text span c="dimmed" className="mono">({r.value})</Text></Text>
                <Text size="xs" fw={600} c={r.impact > 0 ? 'var(--risk)' : 'var(--ok)'}>{r.impact > 0 ? '↑' : '↓'} {Math.abs(r.impact).toFixed(2)}</Text>
              </Group>
            ))}
            <Text size="xs" c="dimmed" mt={4}>Gradient-boosted model with SHAP explanations. It prioritises investigation; it never rejects a claim.</Text>
          </Stack>
        </Paper>
      </Group>
      {!!c.claim_issues?.length && (
        <Alert color="orange" title="Documents disagree with each other">
          {c.claim_issues.map((i) => <Text key={i.code} size="sm">{i.message}</Text>)}
        </Alert>
      )}
      <Paper withBorder p="md">
        <Tabs defaultValue={c.documents[0]?.doc_id}>
          <Tabs.List mb="md">
            {c.documents.map((d) => (
              <Tabs.Tab key={d.doc_id} value={d.doc_id} rightSection={d.review ? '✓' : d.issues?.length ? <Badge size="xs" color="orange">{d.issues.length}</Badge> : null}>
                {d.type ? DOC_TYPE[d.type] : d.name}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          {c.documents.map((d) => (
            <Tabs.Panel key={d.doc_id} value={d.doc_id}><DocumentPanel cid={c.id} doc={d} /></Tabs.Panel>
          ))}
        </Tabs>
      </Paper>
    </Stack>
  );
}
