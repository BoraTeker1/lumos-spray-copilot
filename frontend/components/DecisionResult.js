import {
  CircleCheck,
  CircleHelp,
  Clock,
  OctagonX,
  Search,
  TriangleAlert,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

// One outcome, one look. Wording stays cautious: BLOCK blocks an application,
// nothing here ever instructs anyone to spray.
export const OUTCOME_META = {
  approve: {
    label: "APPROVE",
    icon: CircleCheck,
    box: "border-green-300 bg-green-50",
    text: "text-green-900",
    badge: "green",
    caption: "No conflicts found from entered records",
  },
  block: {
    label: "BLOCK",
    icon: OctagonX,
    box: "border-red-300 bg-red-50",
    text: "text-red-900",
    badge: "red",
    caption: "Conflicts with entered harvest / re-entry timing",
  },
  delay: {
    label: "DELAY",
    icon: Clock,
    box: "border-amber-300 bg-amber-50",
    text: "text-amber-900",
    badge: "amber",
    caption: "A re-entry interval is still active",
  },
  inspect_first: {
    label: "INSPECT FIRST",
    icon: Search,
    box: "border-amber-300 bg-amber-50",
    text: "text-amber-900",
    badge: "amber",
    caption: "No logged scouting evidence for the target",
  },
  pca_review_required: {
    label: "PCA REVIEW REQUIRED",
    icon: CircleHelp,
    box: "border-indigo-300 bg-indigo-50",
    text: "text-indigo-900",
    badge: "indigo",
    caption: "Needs a PCA / agronomist decision",
  },
};

// Human labels for rule-source authority (mirrors app/decision_engine.py).
const AUTHORITY_LABELS = {
  verified_label: "verified label",
  pca_entered: "PCA-entered",
  grower_entered: "grower-entered",
  heuristic: "heuristic",
};

function SourceChip({ rule }) {
  const verified = rule.verification_status === "verified";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
        verified
          ? "bg-green-50 text-green-800 ring-green-600/20"
          : "bg-gray-50 text-gray-600 ring-gray-300"
      }`}
    >
      {AUTHORITY_LABELS[rule.source_authority] || rule.source_authority}
      {" · "}
      {rule.verification_status}
      {rule.entered_by ? ` · ${rule.entered_by}` : ""}
    </span>
  );
}

function InputsList({ inputs }) {
  const shown = Object.entries(inputs || {}).filter(([, v]) => v !== null && v !== undefined);
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] text-gray-600 sm:grid-cols-3">
      {shown.map(([k, v]) => (
        <div key={k} className="flex min-w-0 justify-between gap-2 sm:block">
          <dt className="truncate text-gray-400">{k.replace(/_/g, " ")}</dt>
          <dd className="truncate font-medium text-gray-700">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

// The explainable pre-spray decision: outcome, severity, triggered rules with their
// exact calculations, inputs used, missing information, confidence, and next action.
export default function DecisionResult({ planned, compact = false }) {
  const payload = planned.decision_payload;
  const meta = OUTCOME_META[planned.decision_outcome] || OUTCOME_META.pca_review_required;
  const Icon = meta.icon;
  const triggered = (payload?.rules || []).filter((r) => r.triggered);
  const passed = (payload?.rules || []).filter((r) => !r.triggered);
  const missing = payload?.missing_information || [];
  // Only verified-label / PCA-entered sources can back a definitive verdict; anything
  // else is provisional and says so, loudly, on approve/block.
  const provisional = planned.decision_authority !== "definitive";
  const showProvisionalPrefix =
    provisional && ["approve", "block"].includes(planned.decision_outcome);

  return (
    <div className={`rounded-lg border p-3 ${meta.box}`}>
      {/* Outcome banner */}
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-1.5 text-sm font-bold ${meta.text}`}>
          <Icon className="h-4 w-4" />
          {showProvisionalPrefix ? `PROVISIONAL ${meta.label}` : meta.label}
        </span>
        <span className="text-xs text-gray-600">{meta.caption}</span>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <Badge variant={provisional ? "amber" : "green"}>
          {provisional ? "provisional" : "definitive"}
        </Badge>
        {planned.decision_severity !== "none" && (
          <Badge variant={planned.decision_severity === "critical" ? "red" : "amber"}>
            severity: {planned.decision_severity}
          </Badge>
        )}
        <Badge variant="outline">confidence: {planned.decision_confidence}</Badge>
        {planned.review_required && <Badge variant="indigo">PCA review required</Badge>}
      </div>

      {payload?.authority_basis && (
        <p className="mt-1.5 text-[11px] leading-snug text-gray-600">
          {payload.authority_basis}
        </p>
      )}

      {/* Required next action */}
      <p className={`mt-2 text-sm font-medium ${meta.text}`}>
        Next action: {planned.required_next_action}
      </p>
      {planned.pca_next_action && (
        <p className="mt-1 rounded-md bg-white/70 p-2 text-sm text-gray-800">
          <span className="font-semibold">PCA guidance:</span> {planned.pca_next_action}
        </p>
      )}

      {/* Triggered rules with their calculations */}
      {triggered.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {triggered.map((r) => (
            <li key={r.rule_id} className="rounded-md bg-white/70 p-2 text-xs text-gray-800">
              <div className="flex items-start gap-1.5">
                <TriangleAlert
                  className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                    r.severity === "critical" ? "text-red-600" : "text-amber-600"
                  }`}
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5 font-semibold">
                    {r.name}
                    <SourceChip rule={r} />
                  </div>
                  <p className="mt-0.5">{r.detail}</p>
                  {r.calculation && (
                    <code className="mt-1 block truncate rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-700">
                      {r.calculation}
                    </code>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Missing information */}
      {missing.length > 0 && (
        <div className="mt-2 rounded-md bg-white/70 p-2 text-xs text-gray-700">
          <div className="font-semibold text-gray-800">Missing information</div>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
            {missing.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Checks that ran clean + inputs used (collapsed by default) */}
      {!compact && payload && (
        <details className="mt-2 text-xs text-gray-600">
          <summary className="cursor-pointer select-none font-medium text-gray-500 hover:text-gray-800">
            How this was decided — {passed.length} check(s) passed, inputs used
          </summary>
          <ul className="mt-1.5 space-y-1">
            {passed.map((r) => (
              <li key={r.rule_id} className="flex items-start gap-1.5">
                <CircleCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
                <span>
                  <span className="font-medium">{r.name}:</span> {r.detail}{" "}
                  <SourceChip rule={r} />
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-2 rounded-md bg-white/70 p-2">
            <div className="mb-1 font-semibold text-gray-700">Inputs used</div>
            <InputsList inputs={payload.inputs_used} />
          </div>
        </details>
      )}

      <p className="mt-2 text-[11px] leading-snug text-gray-500">
        {payload?.disclaimer ||
          "PHI and REI checks use values entered by the user and are not independently verified against the current pesticide label."}{" "}
        Decision support only — never a prescription.
      </p>
    </div>
  );
}
