"use client";

import { useState } from "react";
import { CalendarClock } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormError } from "@/components/ui/field";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

// Update a farm's expected harvest date — the resolution action for the
// "harvest date passed" state (a stale date invalidates PHI day-math).
export default function UpdateHarvestDialog({ farmId, currentDate, onUpdated, trigger }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(currentDate || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.updateFarm(farmId, { expected_harvest_date: value || null });
      setOpen(false);
      onUpdated && (await onUpdated());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="secondary" size="sm">
            <CalendarClock />
            Update harvest date
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Update expected harvest date</DialogTitle>
          <DialogDescription>
            PHI checks compute against this date — new pre-spray checks cannot be
            trusted while it is in the past.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={save} className="space-y-3">
          <Input
            type="date"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
            aria-label="Expected harvest date"
          />
          <FormError size="sm">{error}</FormError>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save harvest date"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
