"use client";

import { useState } from "react";
import { Landmark } from "lucide-react";
import { api } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import StatusBadge from "@/components/StatusBadge";

// One indicative financing offer with the grower's one-shot select/decline.
// The copy says "selected", never "accepted" — selecting indicative terms is
// not a loan approval, and no money moves through Lumos.
export default function FinancingOfferCard({ offer, country, canDecide, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(null); // "selected" | "declined" | null

  async function decide(action) {
    setBusy(true);
    setError(null);
    try {
      await api.decideFinancingOffer(offer.id, { action, actor: null });
      setConfirming(null);
      if (onChanged) await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const decidable = canDecide && offer.offer_state === "indicative";

  return (
    <div className="rounded-control border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Landmark className="h-4 w-4 text-info-fg" />
          <span className="text-sm font-semibold text-ink">{offer.provider_name}</span>
        </div>
        <StatusBadge kind="offerState" value={offer.offer_state} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-muted">Requested</dt>
          <dd className="font-medium text-ink">{formatCost(offer.requested_amount, country)}</dd>
        </div>
        <div>
          <dt className="text-muted">Down payment</dt>
          <dd className="font-medium text-ink">{formatCost(offer.down_payment, country)}</dd>
        </div>
        <div>
          <dt className="text-muted">Financed</dt>
          <dd className="font-medium text-ink">{formatCost(offer.financed_amount, country)}</dd>
        </div>
        <div>
          <dt className="text-muted">Total repayment</dt>
          <dd className="font-medium text-ink">{formatCost(offer.total_repayment, country)}</dd>
        </div>
        <div>
          <dt className="text-muted">Fees</dt>
          <dd className="font-medium text-ink">{formatCost(offer.fees_total, country)}</dd>
        </div>
        <div>
          <dt className="text-muted">Expires</dt>
          <dd className="font-medium text-ink">{formatDate(offer.expires_on)}</dd>
        </div>
      </dl>
      {offer.schedule_summary && (
        <p className="mt-2 text-xs text-ink">Schedule: {offer.schedule_summary}</p>
      )}
      {offer.conditions && (
        <p className="mt-1 text-xs text-muted">Conditions: {offer.conditions}</p>
      )}
      {offer.required_documents && (
        <p className="mt-1 text-xs text-muted">Documents: {offer.required_documents}</p>
      )}

      {decidable && !confirming && (
        <div className="mt-3 flex gap-2">
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => setConfirming("selected")}>
            Select indicative terms
          </Button>
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirming("declined")}>
            Decline
          </Button>
        </div>
      )}
      {decidable && confirming && (
        <div className="mt-3 rounded-control border border-info-line bg-info-bg p-3 text-xs text-info-fg">
          {confirming === "selected"
            ? "This selects INDICATIVE terms only — it is not a loan approval, implies no lender confirmation, and any actual financing is arranged directly with the provider."
            : "Decline this indicative offer? This cannot be undone."}
          <div className="mt-2 flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => decide(confirming)}>
              {busy ? "Saving…" : confirming === "selected" ? "Confirm selection" : "Confirm decline"}
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirming(null)}>
              Back
            </Button>
          </div>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-risk-fg">{error}</p>}
      <p className="mt-3 text-[11px] text-muted">{offer.disclaimer}</p>
    </div>
  );
}
