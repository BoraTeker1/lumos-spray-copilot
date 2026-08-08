"use client";

import { useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";

// Every layer's view of one farm, side by side — each either computed or refused.
//
// THREE RULES, each inherited from a specific mistake this codebase already made:
//
// 1. A REFUSAL IS NEVER RENDERED AS A NUMBER OR A BLANK. Same rule as
//    DataReadinessCard. A layer that could not answer says so and shows its reason;
//    it never falls back to `0`, `--`, or an empty card that reads as "nothing to
//    report".
// 2. NO AGGREGATE. There is deliberately no readiness percentage, no overall score,
//    no "3 of 7 layers healthy" progress bar. Counting available layers would weight
//    a transcribed price series equally with a credit assessment. The server refuses
//    to compute one (`farm_profile.not_calculated`) and this card must not invent it.
// 3. THE OWNER SPLIT IS THE POINT. A grower looking at seven refusals cannot tell
//    which are waiting on them and which are waiting on us. `gaps_by_owner` is the
//    one genuinely cross-layer computation the server does, and it is the reason
//    this card exists rather than each page showing its own empty state.
//
// This card is farm-scoped and grower-facing. It must NOT appear on /decisions/[id]:
// the Botrytis shadow study depends on the reviewing PCA not seeing model output.
const OWNER_ORDER = ["grower", "operator", "undetermined"];

const OWNER_INTRO = {
  grower: "Records only you can add:",
  operator: "Waiting on Lumos to transcribe a source document:",
  undetermined: "Not yet classified:",
};

function LayerRow({ layer }) {
  return (
    <div className="flex flex-col gap-0.5 border-l-2 border-line pl-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm text-ink">{layer.label}</span>
        {/* Deliberately not a number and not a dash in a value slot. */}
        <span className="text-xs font-medium text-muted">
          {layer.available ? "Available" : "Not calculated"}
        </span>
      </div>
      {layer.refusal && (
        // Verbatim from the server. These sentences name the specific document or
        // record that would unblock the layer, and paraphrasing loses exactly that.
        <p className="text-xs text-muted">{layer.refusal.detail}</p>
      )}
    </div>
  );
}

export default function FarmProfileCard({ farmId }) {
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!farmId) return;
    let cancelled = false;
    api
      .getFarmProfile(farmId)
      .then((p) => !cancelled && setProfile(p))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [farmId]);

  if (error) {
    return (
      <SectionCard title="Across the platform" icon={<Layers />} size="section">
        <p className="text-sm text-muted">Could not load: {error}</p>
      </SectionCard>
    );
  }
  if (!profile) return null;

  const gaps = profile.gaps_by_owner || {};
  const owners = OWNER_ORDER.filter((o) => (gaps[o] || []).length > 0);

  return (
    <SectionCard
      title="Across the platform"
      icon={<Layers />}
      size="section"
      description="What each layer can say about this farm today, and what is stopping the rest."
    >
      <div className="space-y-4">
        <div className="space-y-2.5">
          {profile.layers.map((layer, i) => (
            <LayerRow key={`${layer.layer}-${i}`} layer={layer} />
          ))}
        </div>

        {owners.length > 0 && (
          <div className="space-y-3 rounded-control border border-line bg-canvas p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">
              What would unblock these
            </div>
            {owners.map((owner) => (
              <div key={owner} className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <StatusBadge kind="gapOwner" value={owner} />
                  <span className="text-xs text-muted">
                    {OWNER_INTRO[owner]} {gaps[owner].length}
                  </span>
                </div>
                <ul className="ml-1 space-y-0.5 text-xs text-muted">
                  {gaps[owner].map((gap, i) => (
                    <li key={`${gap.layer}-${gap.code}-${i}`}>{gap.detail}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {/* The server states why there is no single number; render it rather than
            silently omitting it, so nobody adds one back later thinking it was an
            oversight. */}
        {profile.not_calculated && (
          <ul className="space-y-1 text-xs text-muted">
            {Object.entries(profile.not_calculated).map(([key, reason]) => (
              <li key={key}>{reason}</li>
            ))}
          </ul>
        )}
      </div>
    </SectionCard>
  );
}
