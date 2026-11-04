import { useQuery } from '@tanstack/react-query';

export interface Issue { code: string; field: string; message: string }
export interface FraudReason { feature: string; label: string; value: number; impact: number }

export interface Review { fields: Record<string, unknown>; reviewer: string; at: string; accepted: number; total: number; corrected: string[]; simulated: boolean }

export interface Doc {
  doc_id: string;
  file: string;
  name: string;
  text?: string;
  text_method?: 'pdf_text' | 'ocr';
  ocr_ms?: number;
  type?: DocType;
  type_confidence?: number;
  model?: string;
  served_by?: string;
  fields?: Record<string, unknown> | null;
  error?: string | null;
  issues?: Issue[];
  latency_ms?: number;
  cost_usd?: number;
  tokens_in?: number;
  tokens_out?: number;
  review?: Review;
}

export type DocType = 'claim_form' | 'repair_invoice' | 'accident_statement';
export type ClaimStatus = 'new' | 'processing' | 'review' | 'approved';

export interface Claim {
  id: string;
  ref: string | null;
  source: string;
  status: ClaimStatus;
  received_at: string;
  processed_at?: string;
  documents: Doc[];
  claim_issues?: Issue[];
  fraud?: { score: number | null; reasons: FraudReason[] };
}

export interface ClaimRow {
  id: string;
  ref: string | null;
  status: ClaimStatus;
  received_at: string;
  processed_at?: string;
  docs: number;
  fraud: number | null;
  issues: number;
  models: string[];
}

export interface ModelStats { docs: number; fields: number; accepted: number; acceptance: number | null; cost_per_1k_docs_usd: number | null; avg_latency_ms: number | null }
export interface RouterState {
  champion: string;
  challenger: string | null;
  canary_pct: number;
  auto: boolean;
  history: { at: string; action: string; challenger: string | null; pct?: number; reason: string; auto?: boolean }[];
}
export interface Rollout { state: RouterState; stats: Record<string, ModelStats>; decision: { action: string; reason: string; z?: number } }

export interface EvalSummary {
  endpoint: string;
  model: string;
  at: string;
  docs: number;
  field_accuracy: number;
  doc_exact: number;
  valid_json: number;
  by_group: Record<string, number>;
  tokens_in_avg: number;
  tokens_out_avg: number;
  cost_per_1k_docs_usd: number;
  gpu_cost_per_1k_docs_usd?: number;
  p50_ms: number | null;
  p95_ms: number | null;
}

/** Static build (GitHub Pages): recorded API responses, read-only. */
export const DEMO = import.meta.env.VITE_DEMO === '1';

async function get<T>(path: string): Promise<T> {
  const url = DEMO ? `demo/${path.replaceAll('/', '-')}.json` : `/api/${path}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/api/${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

/** Reviews and canary changes are off: the static demo, or the public AWS demo (protects the rollout statistics). */
export function useReadonly(): boolean {
  const { data } = useQuery({ queryKey: ['health'], queryFn: () => get<{ readonly?: boolean }>('health'), enabled: !DEMO });
  return DEMO || (data?.readonly ?? true);
}

export const api = {
  claims: () => get<ClaimRow[]>('claims'),
  claim: (id: string) => get<Claim>(`claims/${id}`),
  rollout: () => get<Rollout>('rollout'),
  evals: () => get<Record<string, EvalSummary>>('evals'),
  review: (cid: string, docId: string, fields: Record<string, unknown>) => post(`claims/${cid}/documents/${docId}/review`, { fields, reviewer: 'demo-reviewer' }),
  setCanary: (challenger: string | null, pct: number) => post<RouterState>('rollout', { challenger, pct, reason: 'set in the UI' }),
  upload: async (files: File[]) => {
    const body = new FormData();
    files.forEach((f) => body.append('files', f));
    const r = await fetch('/api/claims', { method: 'POST', body });
    if (!r.ok) throw new Error(((await r.json().catch(() => null)) as { detail?: string } | null)?.detail ?? `Upload failed (${r.status})`);
    return r.json() as Promise<Claim>;
  },
  fileUrl: (key: string) => (DEMO ? `demo/${key}` : `/api/${key}`),
};
