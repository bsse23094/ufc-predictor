/** Format a bounded probability for both visible and assistive text. */
export function formatProbability(value: number, locale = "en-US"): string {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new RangeError("probability must be a finite value in [0, 1]");
  }
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  }).format(value);
}
