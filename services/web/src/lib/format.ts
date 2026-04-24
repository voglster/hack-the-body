export const kgToLbs = (kg: number): number => kg * 2.2046226218;

export const formatKg = (kg: number): string => `${kg.toFixed(1)} kg`;

export const formatLbs = (kg: number): string => `${kgToLbs(kg).toFixed(1)} lb`;

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}
