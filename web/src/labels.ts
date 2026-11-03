import type { DocType } from './api';

export const DOC_TYPE: Record<DocType, string> = {
  claim_form: 'Claim form',
  repair_invoice: 'Repair invoice',
  accident_statement: 'Accident statement',
};

export const FIELD: Record<string, string> = {
  policy_number: 'Policy number', claimant_name: 'Claimant', address: 'Address', phone: 'Phone', email: 'E-mail', plate: 'Registration',
  vehicle: 'Vehicle', loss_datetime: 'Loss date and time', loss_location: 'Loss location', description: 'Description',
  estimated_amount_huf: 'Estimate (HUF)', payout_iban: 'Payout IBAN', signed_date: 'Signed', seller_name: 'Repairer',
  seller_tax_number: 'Repairer tax number', invoice_number: 'Invoice number', issue_date: 'Issued', fulfilment_date: 'Fulfilment',
  buyer_name: 'Buyer', line_items: 'Line items', net_total_huf: 'Net total', vat_rate: 'VAT %', vat_huf: 'VAT', gross_total_huf: 'Gross total',
  date: 'Date', time: 'Time', location: 'Location', vehicle_a: 'Vehicle A', vehicle_b: 'Vehicle B', circumstances_a: 'Circumstances A',
  circumstances_b: 'Circumstances B', injuries: 'Injuries', witnesses: 'Witnesses', quantity: 'Qty', unit_price_huf: 'Unit price', net_huf: 'Net', insurer: 'Insurer', driver_name: 'Driver',
};

/** Human name for a model id from the router. */
export function modelName(id: string | null | undefined): string {
  if (!id) return '–';
  if (id === 'champion') return 'Frontier API';
  if (id.startsWith('claimdesk-')) return `Fine-tuned ${id.slice('claimdesk-'.length)}`;
  if (id.startsWith('qwen3-')) return 'Base model, untuned';
  return id;
}

export const huf = (n: number) => `${new Intl.NumberFormat('hu-HU').format(n)} Ft`;
export const pct = (n: number | null | undefined, digits = 1) => (n == null ? '–' : `${(n * 100).toFixed(digits)}%`);
export const usd = (n: number | null | undefined, digits = 2) => (n == null ? '–' : `$${n.toFixed(digits)}`);
