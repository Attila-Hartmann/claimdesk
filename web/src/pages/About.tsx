import { List, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';

const STEPS = [
  ['Read', 'PDF text layer, or Tesseract OCR (Hungarian + English) for scans.'],
  ['Route', 'A TF-IDF + logistic regression classifier picks the document type. No LLM needed, tracked in MLflow.'],
  ['Extract', 'The champion (frontier API) or, for a canary share of traffic, the fine-tuned open-weight model returns schema-checked JSON.'],
  ['Check', 'Deterministic rules: tax-number and IBAN check digits, invoice arithmetic, dates, and cross-document consistency.'],
  ['Score', 'XGBoost fraud model on features from the documents, the policy system and claim history, with SHAP reasons.'],
  ['Review', 'A handler confirms or corrects every field. Each correction is a label for evaluation and for the next fine-tune.'],
];

export function About() {
  return (
    <Stack gap="lg" maw={980}>
      <div>
        <Title order={1}>How it works</Title>
        <Text c="dimmed" mt={6}>
          Claimdesk shows the full lifecycle of an AI model in a regulated back office: from a frontier API on day one to a cheaper
          fine-tuned open-weight model that runs on infrastructure the insurer controls, with the evidence and the safety net to switch.
        </Text>
      </div>
      <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
        {STEPS.map(([t, d], i) => (
          <Paper key={t} withBorder p="md">
            <Text size="xs" c="dimmed" fw={600}>STEP {i + 1}</Text>
            <Text fw={700}>{t}</Text>
            <Text size="sm" mt={4}>{d}</Text>
          </Paper>
        ))}
      </SimpleGrid>
      <Paper withBorder p="md">
        <Title order={3}>The model lifecycle</Title>
        <List mt="sm" spacing={6} size="sm">
          <List.Item>Reviewed extractions become supervised training pairs (here: the synthetic ground truth stands in for them).</List.Item>
          <List.Item>LoRA fine-tuning of Qwen3-4B-Instruct on a rented GPU (Modal); runs, metrics and versions are tracked in MLflow.</List.Item>
          <List.Item>Every version is evaluated on the same held-out documents as the champion before it may see traffic.</List.Item>
          <List.Item>vLLM serves the base model with every adapter version side by side, so a rollout or a rollback is a routing change.</List.Item>
          <List.Item>The canary is judged on handler acceptance with a two-proportion z-test; a regression rolls back automatically.</List.Item>
        </List>
      </Paper>
      <Paper withBorder p="md">
        <Title order={3}>What a production deployment would add</Title>
        <Text size="sm" mt="sm">
          Single sign-on with role-based access, a DPIA and AI Act documentation, retention rules for documents, a real policy
          administration system behind the fraud features, human-labelled data instead of synthetic ground truth, and drift alerts on the
          input documents (new repairers, new layouts).
        </Text>
      </Paper>
    </Stack>
  );
}
