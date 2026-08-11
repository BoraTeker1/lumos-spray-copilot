"use client";

import { useState } from "react";
import { FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import Callout from "@/components/Callout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FormError } from "@/components/ui/field";

// Measured national residue findings (USDA Pesticide Data Program) for one
// (crop, active ingredient) pair.
//
// THREE RULES GOVERN THIS FILE:
//
// 1. NO EXPLANATORY WORDING LIVES HERE. The sentence describing what the numbers mean
//    is `basis_text`, and the scope caveat is `disclaimer` — both owned by the server
//    and rendered verbatim, the DataReadinessCard rule. In particular the RELEASE YEAR
//    is baked into `basis_text` so a card that only wanted the percentage cannot drop
//    it. PDP last sampled fresh strawberries in 2016; a detection rate shown without
//    its year is a different claim from the one the data supports.
//
// 2. A REFUSAL IS RENDERED AS ITS REASON, NEVER AS A ZERO. `pesticide_not_analysed`
//    means the compound was not on the analytical panel — NOT that nothing was found.
//    Showing "0%" there would read as evidence the compound is not a residue concern
//    when in fact nobody looked, and would push toward spraying more.
//
// 3. NO VERDICT, NO BAND, NO SUGGESTED ACTION, ever. The API cannot send one
//    (`ResidueProfile` has no such field). This card must not synthesise one either —
//    no "looks fine", no green tick for a low share of tolerance. Residue history is
//    context for a PCA conversation, not a clearance.
//
// Deliberately NOT placed on /decisions/[id]: adding anything to the PCA-facing
// decision surface breaks the Botrytis shadow study's blinding (ENGINEERING_GUIDELINES.md §5).

function pct(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function Stat({ label, value, hint }) {
  return (
    <div className="flex flex-col gap-0.5 border-l-2 border-line pl-3">
      <span className="text-xs text-muted">{label}</span>
      <span className="text-sm font-semibold tabular-nums text-ink">{value}</span>
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}

function Profile({ data }) {
  return (
    <div className="flex flex-col gap-3">
      {/* Server-owned sentence. Carries the release year — do not summarise it. */}
      <p className="text-sm text-ink">{data.basis_text}</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <Stat
          label="Samples with a detection"
          value={`${data.samples_with_detection} of ${data.samples_tested}`}
          hint={pct(data.detection_rate)}
        />
        {/* Absent, not zero, when nothing was detected — the API omits the key. */}
        {data.max_concentration !== undefined ? (
          <Stat
            label="Highest residue measured"
            value={`${data.max_concentration} ${data.concentration_unit}`}
            hint={
              data.median_detected_concentration !== undefined
                ? `median of detections ${data.median_detected_concentration} ${data.concentration_unit}`
                : undefined
            }
          />
        ) : (
          <Stat label="Highest residue measured" value="None detected" />
        )}
        {data.epa_tolerance_value !== undefined && (
          <Stat
            label="EPA tolerance"
            value={`${data.epa_tolerance_value} ${data.tolerance_unit}`}
            hint="USDA's transcription of the EPA tolerance — not a label value"
          />
        )}
        {data.max_as_share_of_tolerance !== undefined && (
          <Stat
            label="Highest measured, as a share of tolerance"
            value={pct(data.max_as_share_of_tolerance)}
            hint="past national samples, not a prediction for this field"
          />
        )}
      </div>

      {/* A non-numeric tolerance basis (NT / EX / SU) carries meaning as prose. */}
      {data.tolerance_note && <Callout tone="warn">{data.tolerance_note}</Callout>}

      {data.years_since_program >= 5 && (
        <Callout tone="warn" title="Older release">
          USDA has not sampled this commodity for {data.years_since_program} years.
          Growing practice and registered chemistry may have changed since.
        </Callout>
      )}

      <p className="text-xs text-muted">{data.source_reference}</p>
    </div>
  );
}

export default function ResidueReferenceCard({
  defaultCrop = "strawberry",
  defaultActiveIngredient = "",
}) {
  const [crop, setCrop] = useState(defaultCrop);
  const [ai, setAi] = useState(defaultActiveIngredient);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      setData(await api.residueReference(crop, ai));
    } catch (err) {
      setError(err.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <SectionCard
      title="Measured residue history"
      icon={<FlaskConical />}
      description="USDA Pesticide Data Program findings for a crop and active ingredient"
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Crop">
            <Input
              value={crop}
              onChange={(e) => setCrop(e.target.value)}
              placeholder="strawberry"
              required
            />
          </Field>
          <Field label="Active ingredient">
            <Input
              value={ai}
              onChange={(e) => setAi(e.target.value)}
              placeholder="Cyprodinil"
              required
            />
          </Field>
        </div>
        <div>
          <Button type="submit" disabled={loading || !crop || !ai}>
            {loading ? "Looking up…" : "Look up"}
          </Button>
        </div>
      </form>

      {error && <FormError>{error}</FormError>}

      {data && (
        <div className="mt-4 flex flex-col gap-3">
          {data.refused ? (
            // The reason IS the answer here. Never a zero, never an empty card.
            <Callout tone="info" title="Not measured">
              {data.detail}
            </Callout>
          ) : (
            <Profile data={data} />
          )}
          <p className="text-xs text-muted">{data.disclaimer}</p>
        </div>
      )}
    </SectionCard>
  );
}
