"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, CalendarRange, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import SectionCard from "@/components/SectionCard";
import EmptyState from "@/components/EmptyState";
import SaleRecordForm from "@/components/SaleRecordForm";
import {
  BLOCK_OUTCOME_TYPE_LABELS,
  COST_CATEGORY_LABELS,
  CROP_CYCLE_STATUS_LABELS,
  OPERATION_TYPE_LABELS,
} from "@/lib/labels";
import { formatDate } from "@/lib/format";

// The season, and the two things that have never been enterable in this app:
// a non-spray cost, and a measured harvest outcome. `POST /farms/{id}/block-outcomes`
// and both api.js bindings for it have existed with zero UI callers — so a grower
// could not record what the crop actually did, which is the outcome half of the
// whole loop.

const CLOSED_STATUSES = ["closed", "abandoned"];

function StartSeasonForm({ farmId, farm, onDone }) {
  const demoTag = useDemoTag(farmId);
  const [form, setForm] = useState({
    crop: farm?.crop_type || "",
    season_year: String(new Date().getFullYear()),
    season_label: "",
    planting_date: farm?.planting_date || "",
    expected_harvest_start: farm?.expected_harvest_date || "",
    display_area: farm?.greenhouse_area ? String(farm.greenhouse_area) : "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createCropCycle(farmId, {
        ...demoTag,
        crop: form.crop,
        season_year: Number(form.season_year),
        season_label: form.season_label || null,
        planting_date: form.planting_date || null,
        expected_harvest_start: form.expected_harvest_start || null,
        display_area: form.display_area === "" ? null : Number(form.display_area),
        display_area_unit: farm?.area_unit || null,
      });
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Crop" required>
          <Input value={form.crop} onChange={set("crop")} required />
        </Field>
        <Field label="Season year" required>
          <Input type="number" value={form.season_year} onChange={set("season_year")} required />
        </Field>
        <Field label="Season label" hint="What you call it — e.g. “2026 spring plant”.">
          <Input value={form.season_label} onChange={set("season_label")} />
        </Field>
        <Field label={`Planted area (${farm?.area_unit || "unit not set"})`}>
          <Input type="number" step="any" min="0" value={form.display_area} onChange={set("display_area")} />
        </Field>
        <Field label="Planting date">
          <Input type="date" value={form.planting_date} onChange={set("planting_date")} />
        </Field>
        <Field label="Expected harvest start">
          <Input type="date" value={form.expected_harvest_start} onChange={set("expected_harvest_start")} />
        </Field>
      </div>
      <FormError>{error}</FormError>
      <p className="text-[11px] leading-4 text-muted">
        Existing sprays, decisions, scouting and input plans that fall inside this
        window are attached automatically. Records already assigned to another season
        are never moved.
      </p>
      <Button type="submit" disabled={saving || !form.crop}>
        {saving ? "Starting…" : "Start season"}
      </Button>
    </form>
  );
}

function OperationForm({ farmId, cycleId, currency, onDone }) {
  // Without the demo tag this 409s on a demo farm: one farm's records are all demo
  // or all real, and an untagged write defaults to real. The other two forms on this
  // panel already carried it; this one did not, so "Record a cost" was unusable on
  // every seeded farm.
  const demoTag = useDemoTag(farmId);
  const [form, setForm] = useState({
    operation_type: "fertilization",
    cost_category: "",
    performed_on: "",
    cost_amount: "",
    notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createOperation(cycleId, {
        ...demoTag,
        operation_type: form.operation_type,
        // Left blank, the server fills it from the operation type where that is
        // unambiguous and leaves it unset otherwise. It never guesses.
        cost_category: form.cost_category || null,
        performed_on: form.performed_on || null,
        cost_amount: form.cost_amount === "" ? null : Number(form.cost_amount),
        notes: form.notes || null,
      });
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Operation" required>
          <select
            value={form.operation_type}
            onChange={set("operation_type")}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
          >
            {Object.entries(OPERATION_TYPE_LABELS)
              .filter(([key]) => key !== "crop_protection")
              .map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
          </select>
        </Field>
        <Field
          label="Cost category"
          hint="Left as “From the operation type”, the server fills it in where that is unambiguous."
        >
          <select
            value={form.cost_category}
            onChange={set("cost_category")}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
          >
            <option value="">From the operation type</option>
            {Object.entries(COST_CATEGORY_LABELS)
              .filter(([key]) => key !== "uncategorised")
              .map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Performed on">
          <Input type="date" value={form.performed_on} onChange={set("performed_on")} />
        </Field>
        <Field
          label={`Cost${currency ? ` (${currency})` : ""}`}
          hint="Leave blank if unknown — a blank cost is excluded from the season total, never counted as zero."
        >
          <Input type="number" step="any" min="0" value={form.cost_amount} onChange={set("cost_amount")} />
        </Field>
        <Field label="Notes">
          <Input value={form.notes} onChange={set("notes")} />
        </Field>
      </div>
      <FormError>{error}</FormError>
      <p className="text-[11px] leading-4 text-muted">
        Applications are logged as spray events and already carry their own cost —
        this is for the rest of the season&apos;s work.
      </p>
      <Button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Record cost"}
      </Button>
    </form>
  );
}

function HarvestOutcomeForm({ farmId, farm, blocks, onDone, onBlockCreated }) {
  const demoTag = useDemoTag(farmId);
  const [form, setForm] = useState({
    block_id: blocks[0]?.id ? String(blocks[0].id) : "",
    observed_on: "",
    outcome_type: "yield",
    value: "",
    unit: "lb",
    denominator: "",
    method: "",
  });
  // Blocks had a create route and no UI caller at all, so a farm that had never been
  // seeded simply could not record a harvest outcome. Creating one inline is the
  // smallest fix that does not fabricate block structure nobody recorded.
  const [newBlockName, setNewBlockName] = useState("");
  const [creatingBlock, setCreatingBlock] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function createBlock() {
    setCreatingBlock(true);
    setError(null);
    try {
      const block = await api.createBlock(farmId, {
        ...demoTag,
        name: newBlockName,
        crop: farm?.crop_type || null,
      });
      setNewBlockName("");
      setForm((f) => ({ ...f, block_id: String(block.id) }));
      await onBlockCreated?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setCreatingBlock(false);
    }
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createBlockOutcome(farmId, {
        ...demoTag,
        block_id: Number(form.block_id),
        observed_on: form.observed_on,
        outcome_type: form.outcome_type,
        value: form.value === "" ? null : Number(form.value),
        unit: form.unit || null,
        denominator: form.denominator === "" ? null : Number(form.denominator),
        method: form.method || null,
      });
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (blocks.length === 0) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">
          An outcome is measured per block per harvest, not per farm — so this farm
          needs at least one block. Name the one you are harvesting.
        </p>
        <Field label="Block name" required>
          <Input
            value={newBlockName}
            onChange={(e) => setNewBlockName(e.target.value)}
            placeholder="Field 7"
          />
        </Field>
        <FormError>{error}</FormError>
        <Button type="button" onClick={createBlock} disabled={creatingBlock || !newBlockName}>
          {creatingBlock ? "Adding…" : "Add block"}
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Block" required>
          <select
            value={form.block_id}
            onChange={set("block_id")}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
          >
            {blocks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Observed on" required>
          <Input type="date" value={form.observed_on} onChange={set("observed_on")} required />
        </Field>
        <Field label="Measurement" required>
          <select
            value={form.outcome_type}
            onChange={set("outcome_type")}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
          >
            {Object.entries(BLOCK_OUTCOME_TYPE_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Value">
          <Input type="number" step="any" value={form.value} onChange={set("value")} />
        </Field>
        <Field
          label="Unit"
          required
          hint={
            form.outcome_type === "yield"
              ? "Use a weight unit (lb, kg, t) so the season can total a yield. Trays and flats cannot be combined — no source states what one weighs."
              : "Required whenever a value is given — nothing here converts between units."
          }
        >
          <Input value={form.unit} onChange={set("unit")} />
        </Field>
        <Field label="Out of" hint="The denominator a rate refers to — trays graded, berries inspected.">
          <Input type="number" step="any" min="0" value={form.denominator} onChange={set("denominator")} />
        </Field>
      </div>
      <Field label="How it was measured">
        <Input value={form.method} onChange={set("method")} />
      </Field>
      <FormError>{error}</FormError>
      <p className="text-[11px] leading-4 text-muted">
        Append-only: an outcome is never edited. A correction is recorded as a new
        observation that supersedes this one.
      </p>
      <Button type="submit" disabled={saving || !form.observed_on}>
        {saving ? "Saving…" : "Record outcome"}
      </Button>
    </form>
  );
}

export default function SeasonPanel({ farmId, farm, cycles, blocks = [], onChanged }) {
  const [dialog, setDialog] = useState(null);
  const open = cycles.find((c) => !CLOSED_STATUSES.includes(c.status));
  const current = open || cycles[0] || null;

  const close = async () => {
    await api.updateCropCycle(current.id, {
      status: "closed",
      actual_harvest_end: new Date().toISOString().slice(0, 10),
    });
    onChanged?.();
  };

  const done = () => {
    setDialog(null);
    onChanged?.();
  };

  return (
    <SectionCard
      title="Season"
      icon={<CalendarRange className="h-4 w-4 text-muted" aria-hidden />}
      description="The crop cycle every cost, decision and outcome is attributed to."
      action={
        current && (
          <Dialog open={dialog === "operation"} onOpenChange={(v) => setDialog(v ? "operation" : null)}>
            <DialogTrigger asChild>
              <Button variant="secondary" size="sm">
                <Plus className="h-3.5 w-3.5" aria-hidden /> Cost
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Record a season cost</DialogTitle>
                <DialogDescription>
                  A non-spray operation on {current.season_label || current.crop}.
                </DialogDescription>
              </DialogHeader>
              <OperationForm
                farmId={farmId}
                cycleId={current.id}
                currency={current.currency_code}
                onDone={done}
              />
            </DialogContent>
          </Dialog>
        )
      }
    >
      {!current ? (
        <>
          <EmptyState
            title="No season started"
            description="A season is what makes costs, decisions and harvest outcomes add up to one picture."
          />
          <div className="mt-3">
            <StartSeasonForm farmId={farmId} farm={farm} onDone={done} />
          </div>
        </>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink">
              {current.season_label || `${current.season_year} ${current.crop}`}
            </span>
            <Badge variant={CLOSED_STATUSES.includes(current.status) ? "neutral" : "green"}>
              {CROP_CYCLE_STATUS_LABELS[current.status] || current.status}
            </Badge>
          </div>
          <dl className="grid gap-x-4 gap-y-1 text-[11px] text-muted sm:grid-cols-2">
            <div className="flex justify-between gap-2">
              <dt>Planted</dt>
              <dd className="text-ink">{formatDate(current.planting_date) || "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Harvest</dt>
              <dd className="text-ink">
                {formatDate(current.actual_harvest_end || current.expected_harvest_start) || "—"}
              </dd>
            </div>
          </dl>

          <div className="flex flex-wrap gap-2">
            <Dialog open={dialog === "outcome"} onOpenChange={(v) => setDialog(v ? "outcome" : null)}>
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm">
                  <Plus className="h-3.5 w-3.5" aria-hidden /> Harvest outcome
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Record a measured outcome</DialogTitle>
                  <DialogDescription>
                    Yield, packout, cull or disease incidence for one block.
                  </DialogDescription>
                </DialogHeader>
                <HarvestOutcomeForm
                  farmId={farmId}
                  farm={farm}
                  blocks={blocks}
                  onDone={done}
                  onBlockCreated={onChanged}
                />
              </DialogContent>
            </Dialog>

            <Dialog open={dialog === "sale"} onOpenChange={(v) => setDialog(v ? "sale" : null)}>
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm">
                  <Plus className="h-3.5 w-3.5" aria-hidden /> Sale
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Record a sale or settlement</DialogTitle>
                  <DialogDescription>
                    What the crop actually sold for. A recorded transaction only — a
                    market price is never revenue.
                  </DialogDescription>
                </DialogHeader>
                <SaleRecordForm
                  farmId={farmId}
                  cycleId={current.id}
                  currency={current.currency_code}
                  onDone={done}
                />
              </DialogContent>
            </Dialog>

            {!CLOSED_STATUSES.includes(current.status) && (
              <Button variant="ghost" size="sm" onClick={close}>
                Close season
              </Button>
            )}
          </div>

          <Link
            href={`/crop-cycles/${current.id}`}
            className="inline-flex items-center gap-1 text-meta font-medium text-leaf-700 hover:underline"
          >
            {CLOSED_STATUSES.includes(current.status)
              ? "Season closeout"
              : "Season to date"}{" "}
            — cost, yield, revenue
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
        </div>
      )}
    </SectionCard>
  );
}
