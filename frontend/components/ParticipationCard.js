"use client";

import Link from "next/link";
import { Handshake } from "lucide-react";
import { COMMERCIAL_MODEL_LABELS } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";

// How Lumos participates economically in what this farm recorded.
//
// Three facts, in order: what model was agreed → what recorded evidence is the basis
// → what the participation calculates to. That ordering is the point; a figure with
// no visible basis is a bill, and this is not a billing surface.
//
// There is no invoice, no due date, and no paid state — not hidden, absent. See
// app/participation.py, whose dataclass has no field that could carry one.

function Figure({ label, amount, unit, emphasis = false }) {
  if (amount == null) return null;
  const value = Number(amount).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div
        className={
          emphasis
            ? "text-xl font-semibold text-ink"
            : "text-base font-medium text-ink"
        }
      >
        {value} <span className="text-xs font-normal text-muted">{unit}</span>
      </div>
    </div>
  );
}

export default function ParticipationCard({ participation, farmId }) {
  if (!participation) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted">
          No commercial agreement is on record for this farm, so there is no model to
          calculate participation from.
        </p>
        <p className="text-xs text-muted">
          An agreement is entered by Lumos rather than by the grower — it records a
          negotiated term, not a preference.
        </p>
      </div>
    );
  }

  // A refusal is the honest answer whenever the basis has not been measured yet.
  // Never a share of zero: that would read as "Lumos is owed nothing", when the
  // truth is "nothing has been measured".
  if (participation.refused) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted">Not calculated</p>
        <p className="text-xs text-muted">{participation.detail}</p>
      </div>
    );
  }

  const isShare = participation.grower_retained_amount != null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Handshake className="h-4 w-4 text-muted" />
        <span className="font-medium text-ink">{participation.agreement_name}</span>
        <Badge variant="neutral">
          {COMMERCIAL_MODEL_LABELS[participation.model_type] ||
            participation.model_type}
        </Badge>
        {participation.cap_applied && <Badge variant="amber">Cap applied</Badge>}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Figure
          label={participation.basis_label}
          amount={participation.basis_amount}
          unit={participation.basis_unit}
        />
        <Figure
          label="Lumos participation"
          amount={participation.participation_amount}
          unit={participation.participation_unit}
          emphasis
        />
        {isShare && (
          <Figure
            label="Grower retains"
            amount={participation.grower_retained_amount}
            unit={participation.participation_unit}
            emphasis
          />
        )}
      </div>

      <p className="text-xs text-muted">{participation.basis_text}</p>

      {participation.evidence?.length > 0 && (
        <p className="text-[11px] text-muted">
          <span className="font-medium">Evidence: </span>
          {participation.evidence.join(" · ")}
        </p>
      )}
      <p className="text-[11px] text-muted">{participation.disclaimer}</p>
    </div>
  );
}
