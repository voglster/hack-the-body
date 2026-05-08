// Date the user started the current weigh-in protocol. Weight data
// before this is from the old regimen and shouldn't influence trends
// or graphs.
export const PROTOCOL_START_ISO = "2026-04-26";

export function sinceProtocolStart<T extends { ts: string }>(pts: T[]): T[] {
  const cutoff = new Date(PROTOCOL_START_ISO).getTime();
  return pts.filter(p => new Date(p.ts).getTime() >= cutoff);
}
