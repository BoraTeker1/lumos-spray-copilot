// The dense metric tile used in evidence grids — the sibling of MetricCard.
//
// MetricCard is the headline treatment: an icon in a tinted disc, for a row of
// four or five KPIs. StatTile is the same typographic scale WITHOUT the icon,
// for the twelve-tile detail grids where a disc per tile would be noise. They
// share a value scale on purpose, so a number does not appear to change rank
// between the two sections of one page.
//
// This was previously copy-pasted into DecisionEvidenceCard and
// PilotEvidenceCard as a local `Metric`, both carrying a bare `border` — which
// resolves to Tailwind's default gray, not the `line` token every other surface
// in the app uses.
export default function StatTile({ label, value, hint }) {
  return (
    <div className="rounded-control border border-line bg-surface p-3">
      <div className="text-meta text-muted">{label}</div>
      <div className="tabular mt-0.5 text-lg font-semibold text-ink">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] leading-4 text-muted">{hint}</div>}
    </div>
  );
}
