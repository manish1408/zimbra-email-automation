/** Parse Zimbra epoch-ms strings and ISO dates for display. */
export function formatMailDate(value?: string | null): string {
  if (!value) return '—';
  const trimmed = String(value).trim();
  const epoch = /^\d{10,13}$/.test(trimmed) ? Number(trimmed) : NaN;
  let d: Date;
  if (!Number.isNaN(epoch)) {
    d = new Date(trimmed.length <= 10 ? epoch * 1000 : epoch);
  } else {
    d = new Date(trimmed);
  }
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}
