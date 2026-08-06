"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";
import { orderEventLabel } from "@/lib/status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const AVAILABILITIES = ["in_stock", "partial", "backordered", "unknown"];
// input_applied is deliberately absent: it needs the explicit application link
// on the order page — delivery must never be conflated with application.
const POSTABLE_EVENTS = [
  "supplier_confirmed", "shipped", "delivered", "partially_delivered",
  "cancelled", "exception_reported",
];

const labelCls = "block text-xs font-medium text-muted";

// Concierge entry for supplier quotes, indicative financing offers, and order
// lifecycle events (Phase 1 has no supplier portal — Lumos staff transcribe).
export default function ConciergeQuoteCard({ farmId, country }) {
  const [plans, setPlans] = useState([]);
  const [orders, setOrders] = useState([]);
  const [planId, setPlanId] = useState("");
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const [quote, setQuote] = useState({
    supplier_name: "", supplier_contact: "", delivery_cost: "", fees: "",
    payment_terms_cash: "", expected_delivery_date: "", availability: "unknown",
    expires_on: "", notes: "", entered_by: "",
  });
  const [lines, setLines] = useState({}); // item_id -> { unit_price, product_name, substitution_reason }
  const [offer, setOffer] = useState({
    supplier_quote_id: "", provider_name: "", requested_amount: "",
    down_payment: "", total_repayment: "", fees_total: "", schedule_summary: "",
    expires_on: "", conditions: "", entered_by: "",
  });
  const [orderEvent, setOrderEvent] = useState({
    order_id: "", event_type: "supplier_confirmed", occurred_on: "", actor: "",
    notes: "",
  });

  const load = useCallback(async () => {
    try {
      const [p, o] = await Promise.all([
        api.listInputPlans(farmId),
        api.listOrders(farmId),
      ]);
      setPlans(p);
      setOrders(o);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  const quotablePlans = plans.filter((p) =>
    ["submitted_for_quotes", "quoted"].includes(p.status)
  );
  const selectedPlan = plans.find((p) => String(p.id) === planId) || null;
  const [planQuotes, setPlanQuotes] = useState([]);
  useEffect(() => {
    if (!selectedPlan) {
      setPlanQuotes([]);
      return;
    }
    api.listQuotes(selectedPlan.id).then(setPlanQuotes).catch(() => setPlanQuotes([]));
  }, [selectedPlan?.id, status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(fn, okMessage) {
    setBusy(true);
    setStatus(null);
    setError(null);
    try {
      await fn();
      setStatus(okMessage);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function submitQuote(e) {
    e.preventDefault();
    if (!selectedPlan) return setError("Pick a plan first.");
    run(
      () =>
        api.createSupplierQuote(selectedPlan.id, {
          supplier_name: quote.supplier_name,
          supplier_contact: quote.supplier_contact || null,
          delivery_cost: Number(quote.delivery_cost || 0),
          fees: Number(quote.fees || 0),
          payment_terms_cash: quote.payment_terms_cash || null,
          expected_delivery_date: quote.expected_delivery_date || null,
          availability: quote.availability,
          expires_on: quote.expires_on || null,
          notes: quote.notes || null,
          entered_by: quote.entered_by || null,
          items: selectedPlan.items.map((item) => {
            const line = lines[item.id] || {};
            const substituted = (line.product_name || "").trim() &&
              line.product_name.trim() !== item.product_name;
            return {
              input_plan_item_id: item.id,
              product_name: substituted ? line.product_name.trim() : item.product_name,
              is_substitution: Boolean(substituted),
              substitution_reason: substituted ? line.substitution_reason || null : null,
              quantity: item.quantity,
              unit: item.unit,
              unit_price: Number(line.unit_price || 0),
            };
          }),
        }),
      "Quote entered."
    );
  }

  function submitOffer(e) {
    e.preventDefault();
    const requested = Number(offer.requested_amount || 0);
    const down = Number(offer.down_payment || 0);
    run(
      () =>
        api.createFinancingOffer(Number(offer.supplier_quote_id), {
          provider_name: offer.provider_name,
          requested_amount: requested,
          down_payment: down,
          financed_amount: requested - down,
          total_repayment: Number(offer.total_repayment || 0),
          fees_total: Number(offer.fees_total || 0),
          schedule_summary: offer.schedule_summary || null,
          expires_on: offer.expires_on || null,
          conditions: offer.conditions || null,
          entered_by: offer.entered_by || null,
        }),
      "Indicative offer entered (never an approval)."
    );
  }

  function submitOrderEvent(e) {
    e.preventDefault();
    run(
      () =>
        api.addOrderEvent(Number(orderEvent.order_id), {
          event_type: orderEvent.event_type,
          occurred_on: orderEvent.occurred_on,
          actor: orderEvent.actor || null,
          notes: orderEvent.notes || null,
        }),
      "Order event appended."
    );
  }

  return (
    <div className="space-y-6">
      {status && <p className="text-sm text-leaf-700">{status}</p>}
      {error && <p className="text-sm text-risk-fg">{error}</p>}

      <form onSubmit={submitQuote} className="space-y-3">
        <h3 className="text-sm font-semibold text-ink">Enter supplier quote</h3>
        {quotablePlans.length === 0 ? (
          <p className="text-sm text-muted">
            No open RFQs on this farm (a plan must be submitted for quotes first).
          </p>
        ) : (
          <>
            <label className={labelCls}>
              Open RFQ
              <Select value={planId} onChange={(e) => setPlanId(e.target.value)} className="mt-1">
                <option value="">Pick a plan…</option>
                {quotablePlans.map((p) => (
                  <option key={p.id} value={p.id}>
                    Plan #{p.id} — {p.items.map((i) => i.product_name).join(", ")}
                  </option>
                ))}
              </Select>
            </label>
            {selectedPlan && (
              <>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <label className={labelCls}>
                    Supplier *
                    <Input value={quote.supplier_name} onChange={(e) => setQuote({ ...quote, supplier_name: e.target.value })} className="mt-1" />
                  </label>
                  <label className={labelCls}>
                    Delivery cost
                    <Input type="number" step="any" min="0" value={quote.delivery_cost} onChange={(e) => setQuote({ ...quote, delivery_cost: e.target.value })} className="mt-1" />
                  </label>
                  <label className={labelCls}>
                    Fees / taxes
                    <Input type="number" step="any" min="0" value={quote.fees} onChange={(e) => setQuote({ ...quote, fees: e.target.value })} className="mt-1" />
                  </label>
                  <label className={labelCls}>
                    Cash terms
                    <Input value={quote.payment_terms_cash} onChange={(e) => setQuote({ ...quote, payment_terms_cash: e.target.value })} placeholder="Net 30…" className="mt-1" />
                  </label>
                  <label className={labelCls}>
                    Expected delivery
                    <Input type="date" value={quote.expected_delivery_date} onChange={(e) => setQuote({ ...quote, expected_delivery_date: e.target.value })} className="mt-1" />
                  </label>
                  <label className={labelCls}>
                    Availability
                    <Select value={quote.availability} onChange={(e) => setQuote({ ...quote, availability: e.target.value })} className="mt-1">
                      {AVAILABILITIES.map((a) => (
                        <option key={a} value={a}>{a}</option>
                      ))}
                    </Select>
                  </label>
                  <label className={labelCls}>
                    Quote expires
                    <Input type="date" value={quote.expires_on} onChange={(e) => setQuote({ ...quote, expires_on: e.target.value })} className="mt-1" />
                  </label>
                  <label className={labelCls}>
                    Entered by
                    <Input value={quote.entered_by} onChange={(e) => setQuote({ ...quote, entered_by: e.target.value })} className="mt-1" />
                  </label>
                </div>
                <div className="space-y-2 rounded-control border border-line p-3">
                  {selectedPlan.items.map((item) => (
                    <div key={item.id} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <div className="text-xs text-ink sm:col-span-1">
                        <div className="font-medium">{item.product_name}</div>
                        <div className="text-muted">{item.quantity} {item.unit}</div>
                      </div>
                      <label className={labelCls}>
                        Unit price *
                        <Input type="number" step="any" min="0" value={lines[item.id]?.unit_price || ""} onChange={(e) => setLines({ ...lines, [item.id]: { ...lines[item.id], unit_price: e.target.value } })} className="mt-1" />
                      </label>
                      <label className={labelCls}>
                        Substitute product (optional)
                        <Input value={lines[item.id]?.product_name || ""} onChange={(e) => setLines({ ...lines, [item.id]: { ...lines[item.id], product_name: e.target.value } })} className="mt-1" />
                      </label>
                      <label className={labelCls}>
                        Substitution reason
                        <Input value={lines[item.id]?.substitution_reason || ""} onChange={(e) => setLines({ ...lines, [item.id]: { ...lines[item.id], substitution_reason: e.target.value } })} className="mt-1" />
                      </label>
                    </div>
                  ))}
                </div>
                <Button type="submit" disabled={busy}>
                  {busy ? "Saving…" : "Enter quote"}
                </Button>
              </>
            )}
          </>
        )}
      </form>

      <form onSubmit={submitOffer} className="space-y-3 border-t border-line pt-4">
        <h3 className="text-sm font-semibold text-ink">
          Enter indicative financing offer
        </h3>
        <p className="text-xs text-muted">
          Manually collected terms only — never a credit decision, and only
          possible when the grower requested financing on the plan.
        </p>
        {!selectedPlan || planQuotes.length === 0 ? (
          <p className="text-sm text-muted">Pick a plan with quotes above first.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <label className={labelCls}>
                Against quote
                <Select value={offer.supplier_quote_id} onChange={(e) => setOffer({ ...offer, supplier_quote_id: e.target.value })} className="mt-1">
                  <option value="">Pick a quote…</option>
                  {planQuotes.filter((q) => q.status !== "withdrawn").map((q) => (
                    <option key={q.id} value={q.id}>
                      #{q.id} {q.supplier_name} ({formatCost(q.total_cost, country)})
                    </option>
                  ))}
                </Select>
              </label>
              <label className={labelCls}>
                Provider *
                <Input value={offer.provider_name} onChange={(e) => setOffer({ ...offer, provider_name: e.target.value })} className="mt-1" />
              </label>
              <label className={labelCls}>
                Requested amount *
                <Input type="number" step="any" min="0" value={offer.requested_amount} onChange={(e) => setOffer({ ...offer, requested_amount: e.target.value })} className="mt-1" />
              </label>
              <label className={labelCls}>
                Down payment
                <Input type="number" step="any" min="0" value={offer.down_payment} onChange={(e) => setOffer({ ...offer, down_payment: e.target.value })} className="mt-1" />
              </label>
              <label className={labelCls}>
                Total repayment *
                <Input type="number" step="any" min="0" value={offer.total_repayment} onChange={(e) => setOffer({ ...offer, total_repayment: e.target.value })} className="mt-1" />
              </label>
              <label className={labelCls}>
                Fees
                <Input type="number" step="any" min="0" value={offer.fees_total} onChange={(e) => setOffer({ ...offer, fees_total: e.target.value })} className="mt-1" />
              </label>
              <label className={labelCls}>
                Schedule summary
                <Input value={offer.schedule_summary} onChange={(e) => setOffer({ ...offer, schedule_summary: e.target.value })} placeholder="3 monthly payments of…" className="mt-1" />
              </label>
              <label className={labelCls}>
                Offer expires
                <Input type="date" value={offer.expires_on} onChange={(e) => setOffer({ ...offer, expires_on: e.target.value })} className="mt-1" />
              </label>
              <label className={labelCls}>
                Entered by
                <Input value={offer.entered_by} onChange={(e) => setOffer({ ...offer, entered_by: e.target.value })} className="mt-1" />
              </label>
            </div>
            <Textarea value={offer.conditions} onChange={(e) => setOffer({ ...offer, conditions: e.target.value })} placeholder="Conditions (optional)" className="h-16" />
            <Button type="submit" disabled={busy || !offer.supplier_quote_id}>
              {busy ? "Saving…" : "Enter indicative offer"}
            </Button>
          </>
        )}
      </form>

      <form onSubmit={submitOrderEvent} className="space-y-3 border-t border-line pt-4">
        <h3 className="text-sm font-semibold text-ink">Append order event</h3>
        <p className="text-xs text-muted">
          Append-only lifecycle events. “Input applied” is not postable here — it
          requires the explicit application link on the order page.
        </p>
        {orders.length === 0 ? (
          <p className="text-sm text-muted">No orders on this farm yet.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <label className={labelCls}>
                Order
                <Select value={orderEvent.order_id} onChange={(e) => setOrderEvent({ ...orderEvent, order_id: e.target.value })} className="mt-1">
                  <option value="">Pick an order…</option>
                  {orders.map((o) => (
                    <option key={o.id} value={o.id}>
                      #{o.id} {o.supplier_name} ({o.status})
                    </option>
                  ))}
                </Select>
              </label>
              <label className={labelCls}>
                Event
                <Select value={orderEvent.event_type} onChange={(e) => setOrderEvent({ ...orderEvent, event_type: e.target.value })} className="mt-1">
                  {POSTABLE_EVENTS.map((ev) => (
                    <option key={ev} value={ev}>{orderEventLabel(ev)}</option>
                  ))}
                </Select>
              </label>
              <label className={labelCls}>
                Occurred on *
                <Input type="date" value={orderEvent.occurred_on} onChange={(e) => setOrderEvent({ ...orderEvent, occurred_on: e.target.value })} className="mt-1" />
              </label>
              <label className={labelCls}>
                Actor
                <Input value={orderEvent.actor} onChange={(e) => setOrderEvent({ ...orderEvent, actor: e.target.value })} className="mt-1" />
              </label>
            </div>
            <Input value={orderEvent.notes} onChange={(e) => setOrderEvent({ ...orderEvent, notes: e.target.value })} placeholder="Notes (optional)" />
            <Button type="submit" disabled={busy || !orderEvent.order_id || !orderEvent.occurred_on}>
              {busy ? "Saving…" : "Append event"}
            </Button>
          </>
        )}
      </form>
    </div>
  );
}
