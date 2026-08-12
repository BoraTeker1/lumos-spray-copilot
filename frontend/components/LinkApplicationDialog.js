"use client";

import { useEffect, useState } from "react";
import { Droplets } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { FormError } from "@/components/ui/field";

// Explicitly link a delivered order to the actual application record.
// Delivery never marks an input as applied — this dialog is the only path.
export default function LinkApplicationDialog({ order, onChanged }) {
  const [open, setOpen] = useState(false);
  const [sprays, setSprays] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [choice, setChoice] = useState(""); // "spray:<id>" | "decision:<id>"
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    Promise.all([
      api.listSprayEvents(order.farm_id),
      api.listPlannedSprays(order.farm_id),
    ])
      .then(([s, p]) => {
        setSprays(s);
        // Only decisions with an APPLIED outcome can be "what was applied".
        setDecisions(
          p.filter((d) => ["sprayed_as_planned", "changed_product"].includes(d.outcome))
        );
      })
      .catch((err) => setError(err.message));
  }, [open, order.farm_id]);

  async function submit(e) {
    e.preventDefault();
    if (!choice) {
      setError("Pick the application record that used this order's input.");
      return;
    }
    const [kind, id] = choice.split(":");
    setSaving(true);
    setError(null);
    try {
      await api.reportInputApplied(order.id, {
        spray_event_id: kind === "spray" ? Number(id) : null,
        planned_spray_id: kind === "decision" ? Number(id) : null,
      });
      setOpen(false);
      if (onChanged) await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm">
          <Droplets />
          Record input applied
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Record input applied</DialogTitle>
          <DialogDescription>
            Delivery never marks an input as applied — link the actual
            application record (a logged spray or an applied decision).
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <Select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Choose the application record…</option>
            {decisions.length > 0 && (
              <optgroup label="Applied decisions">
                {decisions.map((d) => (
                  <option key={`d-${d.id}`} value={`decision:${d.id}`}>
                    #{d.id} — {d.outcome_product_name || d.product_name} (
                    {formatDate(d.outcome_date || d.intended_date)})
                  </option>
                ))}
              </optgroup>
            )}
            {sprays.length > 0 && (
              <optgroup label="Logged applications">
                {sprays.map((s) => (
                  <option key={`s-${s.id}`} value={`spray:${s.id}`}>
                    {s.product_name} ({formatDate(s.application_date)})
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
          <FormError>{error}</FormError>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Link application"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
