// Measured results (WEB-03). Figures appear only from a dated results file, each under the
// required label (spec/00 honesty rules). Without a file the section says results are not yet published.

export function readResults(data) {
  if (!data) return { published: false, figures: [], label: null };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(data.date ?? "")) throw new Error("results file needs a date (YYYY-MM-DD)");
  const figures = (data.figures ?? []).map((f) => {
    if (!f.caption) throw new Error("every figure needs a caption");
    return { value: String(f.value), caption: f.caption };
  });
  return {
    published: true,
    figures,
    label: `Test-network evaluation on synthetic data, ${data.date}. Not production results.`,
  };
}
