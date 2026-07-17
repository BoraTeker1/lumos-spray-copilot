"use client";

import { useState } from "react";
import { Landmark } from "lucide-react";
import { api } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import StatusBadge from "@/components/StatusBadge";

// One indicative financing offer with the grower's one-shot accept/decline.
// The copy never lets "accepted" read as a loan approval — no approval
// happened, and no money moves through Lumos.
export default function FinancingOfferCard({ offer, country, canDecide, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(null); // "accepted" | "declined" | null

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
    <div className="rounded-md border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Landmark className="h-4 w-4 text-blue-600" />
          <span className="text-sm font-semibold text-gray-900">{offer.provider_name}</span>
        </div>
        <StatusBadge kind="offerState" value={offer.offer_state} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-gray-500">Requested</dt>
          <dd className="font-medium text-gray-900">{formatCost(offer.requested_amount, country)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Down payment</dt>
          <dd className="font-medium text-gray-900">{formatCost(offer.down_payment, country)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Financed</dt>
          <dd className="font-medium text-gray-900">{formatCost(offer.financed_amount, country)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Total repayment</dt>
          <dd className="font-medium text-gray-900">{formatCost(offer.total_repayment, country)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Fees</dt>
          <dd className="font-medium text-gray-900">{formatCost(offer.fees_total, country)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Expires</dt>
          <dd className="font-medium text-gray-900">{formatDate(offer.expires_on)}</dd>
        </div>
      </dl>
      {offer.schedule_summary && (
        <p className="mt-2 text-xs text-gray-700">Schedule: {offer.schedule_summary}</p>
      )}
      {offer.conditions && (
        <p className="mt-1 text-xs text-gray-500">Conditions: {offer.conditions}</p>
      )}
      {offer.required_documents && (
        <p className="mt-1 text-xs text-gray-500">Documents: {offer.required_documents}</p>
      )}

      {decidable && !confirming && (
        <div className="mt-3 flex gap-2">
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => setConfirming("accepted")}>
            Accept indicative terms
          </Button>
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirming("declined")}>
            Decline
          </Button>
        </div>
      )}
      {decidable && confirming && (
        <div className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900">
          {confirming === "accepted"
            ? "This accepts INDICATIVE terms only — it is not a loan approval, and any actual financing is arranged directly with the provider."
            : "Decline this indicative offer? This cannot be undone."}
          <div className="mt-2 flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => decide(confirming)}>
              {busy ? "Saving…" : confirming === "accepted" ? "Confirm accept" : "Confirm decline"}
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirming(null)}>
              Back
            </Button>
          </div>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <p className="mt-3 text-[11px] text-gray-500">{offer.disclaimer}</p>
    </div>
  );
}
