"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import { Database } from "lucide-react";
import { FormError } from "@/components/ui/field";

// Whether this farm's data can yet support a measurement.
//
// TWO RULES GOVERN THIS FILE, and both exist because of specific past mistakes:
//
// 1. NO EXPLANATORY WORDING LIVES HERE. The sentence describing where these numbers
//    come from is `basis_text`, owned by the server. Four compliance surfaces once
//    each hardcoded their own version of that sentence and drifted apart, and none of
//    them could become conditional on what the farm actually had. Do not add a
//    reassuring paragraph to this component — extend `_data_readiness_basis_text`.
//
// 2. AN ABSTENTION IS NEVER RENDERED AS A NUMBER. The API sends either
//    `{value, unit}` or `{abstained, reasons}` and never a null `value`, precisely so
//    this component cannot accidentally show `0`. "0 leaf-wetness hours" is not a
//    data gap, it reads as "no wetness occurred" — the opposite of the truth, in the
//    direction that would make someone skip a spray they needed.
//
// This card shows no risk band and no suggested action, and must never acquire one:
// that would break the Botrytis shadow study's blinding and turn a data-quality
// surface into a spray prompt.

// Display names only. The abstention REASONS are rendered verbatim from the server —
// they are the actionable part ("no station configured", "3 of 11 applications have
// no MoA group"), and paraphrasing them here would lose the specificity.
const MEASURE_LABELS = {
  weather_observation_coverage_pct: "Weather coverage",
  weather_data_staleness_hours: "Weather freshness",
  leaf_wetness_hours: "Leaf wetness",
  active_ingredient_kg_per_ha: "Active ingredient applied",
  moa_rotation_diversity: "MoA rotation diversity",
  scouting_recency_days: "Scouting recency",
};

const UNIT_SUFFIX = {
  pct: "%",
  h: " h",
  d: " days",
  "kg/ha": " kg/ha",
  ratio: "",
};

function formatValue(measure) {
  const suffix = UNIT_SUFFIX[measure.unit] ?? ` ${measure.unit ?? ""}`;
  return `${measure.value}${suffix}`;
}

function Measure({ name, measure }) {
  const label = MEASURE_LABELS[name] || name;

  if (measure.abstained) {
    return (
      <div className="flex flex-col gap-0.5 border-l-2 border-line pl-3">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm text-ink">{label}</span>
          {/* Deliberately not a number, not a dash-in-a-value-slot. */}
          <span className="text-xs font-medium text-muted">Not calculated</span>
        </div>
        <ul className="text-xs text-muted">
          {measure.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="flex items-baseline justify-between gap-2 border-l-2 border-ok-line pl-3">
      <span className="text-sm text-ink">{label}</span>
      <span className="text-sm font-semibold tabular-nums text-ink">
        {formatValue(measure)}
      </span>
    </div>
  );
}

function EntityGroup({ title, entries }) {
  if (!entries?.length) return null;
  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
        {title}
      </h4>
      {entries.map((entry) => (
        <div key={entry.entity_id} className="flex flex-col gap-2">
          {Object.entries(entry.measures).map(([name, measure]) => (
            <Measure key={name} name={name} measure={measure} />
          ))}
        </div>
      ))}
    </div>
  );
}

export default function DataReadinessCard({ farmId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getDataReadiness(farmId)
      .then((body) => !cancelled && setData(body))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [farmId]);

  if (error) {
    return (
      <SectionCard title="Data readiness" icon={<Database />}>
        <FormError>{error}</FormError>
      </SectionCard>
    );
  }
  if (!data) {
    return (
      <SectionCard title="Data readiness" icon={<Database />}>
        <p className="text-sm text-muted">Loading…</p>
      </SectionCard>
    );
  }

  const hasAny =
    data.fields.length || data.crop_cycles.length || data.blocks.length;

  return (
    <SectionCard
      title="Data readiness"
      icon={<Database />}
      description="What this farm's data can and cannot yet measure"
    >
      <div className="flex flex-col gap-4">
        {hasAny ? (
          <>
            <EntityGroup title="Fields" entries={data.fields} />
            <EntityGroup title="Crop cycles" entries={data.crop_cycles} />
            <EntityGroup title="Blocks" entries={data.blocks} />
          </>
        ) : (
          <p className="text-sm text-muted">
            No measures have been computed for this farm yet.
          </p>
        )}

        {/* Server-owned. Never replace this with wording written in the component. */}
        <p className="border-t pt-3 text-xs text-muted">{data.basis_text}</p>
      </div>
    </SectionCard>
  );
}
