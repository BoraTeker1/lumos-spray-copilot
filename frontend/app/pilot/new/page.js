"use client";

import { useState } from "react";
import Link from "next/link";
import { Droplets, Eye, Gauge, Info, Sprout } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fieldClass } from "@/components/ui/input";
import PageHeader from "@/components/PageHeader";
import SectionCard from "@/components/SectionCard";
import SprayImportCard from "@/components/SprayImportCard";
import { FormError } from "@/components/ui/field";

const EMPTY_SPRAY = {
  product_name: "",
  active_ingredient: "",
  application_date: "",
  cost: "",
  pre_harvest_interval_days: "",
  re_entry_interval_hours: "",
};

// Local-demo-friendly intake: capture a real pilot farm + its last 3 sprays + a concern.
export default function PilotFarmIntakePage() {
  const [createdFarm, setCreatedFarm] = useState(null);
  const [farm, setFarm] = useState({
    name: "",
    location: "",
    country: "US",
    crop_type: "strawberry",
    greenhouse_area: "",
    expected_harvest_date: "",
    advisor_involved: "",
  });
  const [sprays, setSprays] = useState([{ ...EMPTY_SPRAY }, { ...EMPTY_SPRAY }, { ...EMPTY_SPRAY }]);
  const [concern, setConcern] = useState({ text: "", severity: "" });
  // The reduction denominator. Asked here because it is a 20-second question during
  // onboarding and an awkward one six weeks later — and without it the farm can never
  // report a reduction figure at all.
  const [baseline, setBaseline] = useState({
    method: "",
    cadence_days: "",
    season_spray_count: "",
    calendar_program: "",
    baseline_period_start: "",
    baseline_period_end: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const setFarmField = (k, v) => setFarm((f) => ({ ...f, [k]: v }));
  const setSpray = (i, k, v) =>
    setSprays((rows) => rows.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)));

  function cleanSpray(s) {
    if (!s.product_name) return null;
    return {
      product_name: s.product_name,
      active_ingredient: s.active_ingredient || null,
      application_date: s.application_date || null,
      cost: s.cost === "" ? null : Number(s.cost),
      pre_harvest_interval_days:
        s.pre_harvest_interval_days === "" ? null : Number(s.pre_harvest_interval_days),
      re_entry_interval_hours:
        s.re_entry_interval_hours === "" ? null : Number(s.re_entry_interval_hours),
    };
  }

  // Only the fields the chosen method actually uses are sent — a cadence left over
  // from switching method must not travel with a prior_period baseline.
  function cleanBaseline() {
    if (!baseline.method) return null;
    const b = {
      method: baseline.method,
      declared_by: "Grower, at intake",
      cadence_days: null,
      season_spray_count: null,
      calendar_program: null,
      baseline_period_start: null,
      baseline_period_end: null,
    };
    if (baseline.method === "stated_cadence") {
      if (baseline.cadence_days === "") return null;
      b.cadence_days = Number(baseline.cadence_days);
    } else if (baseline.method === "calendar_program") {
      if (!baseline.calendar_program) return null;
      b.calendar_program = baseline.calendar_program;
    } else if (baseline.method === "prior_period") {
      if (baseline.season_spray_count === "") return null;
      b.season_spray_count = Number(baseline.season_spray_count);
      b.baseline_period_start = baseline.baseline_period_start || null;
      b.baseline_period_end = baseline.baseline_period_end || null;
    }
    return b;
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: farm.name,
        location: farm.location || null,
        country: farm.country,
        crop_type: farm.crop_type,
        greenhouse_area: farm.greenhouse_area === "" ? null : Number(farm.greenhouse_area),
        expected_harvest_date: farm.expected_harvest_date || null,
        advisor_involved:
          farm.advisor_involved === "" ? null : farm.advisor_involved === "yes",
        spray_events: sprays.map(cleanSpray).filter(Boolean),
        scouting_concern: concern.text || null,
        scouting_severity_1_to_5: concern.severity === "" ? null : Number(concern.severity),
        spray_baseline: cleanBaseline(),
      };
      const created = await api.createPilotFarm(payload);
      // Stay on this page: offer the full spray-history import before opening the farm.
      setCreatedFarm(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const input = fieldClass;
  const label = "text-xs font-medium text-muted";

  if (createdFarm) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-lg font-semibold">
            {createdFarm.name} created
          </h1>
          <p className="mt-1 text-sm text-muted">
            Optional: import their full spray history now — paste rows from a
            spreadsheet or upload a CSV. You can also do this later from the farm&apos;s
            Records tab.
          </p>
        </div>
        <section className="rounded-card border border-line bg-surface p-5 shadow-sm">
          <h2 className="mb-3 font-semibold">Import spray history</h2>
          <SprayImportCard farmId={createdFarm.id} />
        </section>
        <Link
          href={`/farms/${createdFarm.id}`}
          className="inline-block rounded-control bg-leaf-700 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-leaf-800"
        >
          Open {createdFarm.name} →
        </Link>
      </div>
    );
  }

  return (
    // ONE flat page, ONE submit. Deliberately not a wizard: this intake is a
    // single POST, and a stepper would add flow state and gating that the
    // request does not have.
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Pilot setup" }]}
        title="Add pilot farm"
        meta={
          <>
            <Badge variant="outline">Real operations intake</Badge>
            <span>
              Capture the farm, recent spray history, and the latest scouting concern
              before running the next planned-spray check.
            </span>
          </>
        }
      />

      <div className="flex items-start gap-2 rounded-card border border-line bg-canvas px-4 py-2.5 text-sm text-muted">
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        Records entered here are operator-provided until reviewed. Regulatory values
        are never guessed — leave a field blank if you do not have it.
      </div>

      <form onSubmit={submit} className="space-y-4">
        {/* Farm */}
        <SectionCard title="Farm details" icon={<Sprout />} size="section">
        <section className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <span className={label}>Farm name *</span>
            <input className={input} required value={farm.name} onChange={(e) => setFarmField("name", e.target.value)} />
          </div>
          <div>
            <span className={label}>Region / location</span>
            <input className={input} value={farm.location} onChange={(e) => setFarmField("location", e.target.value)} placeholder="Watsonville, California" />
          </div>
          <div>
            <span className={label}>Country</span>
            <select className={input} value={farm.country} onChange={(e) => setFarmField("country", e.target.value)}>
              <option value="US">US</option>
              <option value="TR">TR</option>
            </select>
          </div>
          <div>
            <span className={label}>Crop</span>
            <input className={input} value={farm.crop_type} onChange={(e) => setFarmField("crop_type", e.target.value)} placeholder="strawberry" />
          </div>
          <div>
            <span className={label}>Area ({farm.country === "TR" ? "m²" : "acres"})</span>
            <input type="number" step="0.1" className={input} value={farm.greenhouse_area} onChange={(e) => setFarmField("greenhouse_area", e.target.value)} />
          </div>
          <div>
            <span className={label}>Expected harvest date</span>
            <input type="date" className={input} value={farm.expected_harvest_date} onChange={(e) => setFarmField("expected_harvest_date", e.target.value)} />
          </div>
          <div>
            <span className={label}>PCA / agronomist already involved?</span>
            <select className={input} value={farm.advisor_involved} onChange={(e) => setFarmField("advisor_involved", e.target.value)}>
              <option value="">—</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </div>
        </section>
        </SectionCard>

        {/* Last 3 sprays */}
        <SectionCard
          title="Last 3 spray events"
          icon={<Droplets />}
          size="section"
          description="Recent chemistry and timing give the rotation and interval checks something to work from."
        >
          {/* A column-header row once, instead of a placeholder in all eighteen
              inputs: a placeholder is not a label, and it disappears exactly when
              the person needs to check which column they are in. The headers are
              hidden on one-column mobile, where each input needs its own label. */}
          <div className="space-y-3">
            <div className="hidden gap-2 sm:grid sm:grid-cols-6">
              {[
                "Product",
                "Active ingredient",
                "Date",
                "Cost",
                "PHI days",
                "REI hours",
              ].map((h) => (
                <span
                  key={h}
                  className="text-[11px] font-semibold uppercase tracking-wider text-muted"
                >
                  {h}
                </span>
              ))}
            </div>
            {sprays.map((s, i) => (
              <div key={i} className="grid grid-cols-1 gap-2 sm:grid-cols-6">
                <input className={input} aria-label={`Spray ${i + 1} product`} placeholder="Product" value={s.product_name} onChange={(e) => setSpray(i, "product_name", e.target.value)} />
                <input className={input} aria-label={`Spray ${i + 1} active ingredient`} placeholder="Active ingredient" value={s.active_ingredient} onChange={(e) => setSpray(i, "active_ingredient", e.target.value)} />
                <input type="date" className={input} aria-label={`Spray ${i + 1} date`} value={s.application_date} onChange={(e) => setSpray(i, "application_date", e.target.value)} />
                <input type="number" className={input} aria-label={`Spray ${i + 1} cost`} placeholder="Cost" value={s.cost} onChange={(e) => setSpray(i, "cost", e.target.value)} />
                <input type="number" className={input} aria-label={`Spray ${i + 1} PHI days`} placeholder="PHI days" value={s.pre_harvest_interval_days} onChange={(e) => setSpray(i, "pre_harvest_interval_days", e.target.value)} />
                <input type="number" className={input} aria-label={`Spray ${i + 1} REI hours`} placeholder="REI hours" value={s.re_entry_interval_hours} onChange={(e) => setSpray(i, "re_entry_interval_hours", e.target.value)} />
              </div>
            ))}
          </div>
          <p className="mt-3 text-meta text-muted">Leave a row blank to skip it.</p>
        </SectionCard>

        {/* Spray baseline — the reduction denominator */}
        <SectionCard
          title="Spray baseline"
          icon={<Gauge />}
          size="section"
          description="What their normal programme looks like, in their words. Without this, Lumos cannot report a reduction figure for this farm at all — it has nothing to measure against."
        >
          <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <span className={label}>How do they describe it?</span>
              <select
                className={input}
                value={baseline.method}
                onChange={(e) => setBaseline((b) => ({ ...b, method: e.target.value }))}
              >
                <option value="">Skip for now</option>
                <option value="stated_cadence">They spray every N days</option>
                <option value="calendar_program">A named calendar programme</option>
                <option value="prior_period">A count from a past season</option>
              </select>
            </div>

            {baseline.method === "stated_cadence" && (
              <div>
                <span className={label}>Every how many days?</span>
                <input
                  type="number"
                  min="1"
                  className={input}
                  value={baseline.cadence_days}
                  onChange={(e) => setBaseline((b) => ({ ...b, cadence_days: e.target.value }))}
                  placeholder="7"
                />
              </div>
            )}

            {baseline.method === "calendar_program" && (
              <div>
                <span className={label}>Which programme?</span>
                <select
                  className={input}
                  value={baseline.calendar_program}
                  onChange={(e) =>
                    setBaseline((b) => ({ ...b, calendar_program: e.target.value }))
                  }
                >
                  <option value="">—</option>
                  <option value="weekly">Weekly</option>
                  <option value="every_10_days">Every 10 days</option>
                  <option value="biweekly">Every 2 weeks</option>
                  <option value="every_3_weeks">Every 3 weeks</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>
            )}

            {baseline.method === "prior_period" && (
              <>
                <div>
                  <span className={label}>Sprays in that period</span>
                  <input
                    type="number"
                    min="1"
                    className={input}
                    value={baseline.season_spray_count}
                    onChange={(e) =>
                      setBaseline((b) => ({ ...b, season_spray_count: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <span className={label}>Period start</span>
                  <input
                    type="date"
                    className={input}
                    value={baseline.baseline_period_start}
                    onChange={(e) =>
                      setBaseline((b) => ({ ...b, baseline_period_start: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <span className={label}>Period end</span>
                  <input
                    type="date"
                    className={input}
                    value={baseline.baseline_period_end}
                    onChange={(e) =>
                      setBaseline((b) => ({ ...b, baseline_period_end: e.target.value }))
                    }
                  />
                </div>
              </>
            )}
          </section>
          <p className="mt-2 text-xs text-muted">
            Recorded as the grower&apos;s own statement, not a Lumos estimate. An early or
            weak figure is still reported as illustrative until enough real sprays are
            logged against it.
          </p>
        </SectionCard>

        {/* Scouting concern */}
        <SectionCard
          title="Latest scouting concern"
          icon={<Eye />}
          size="section"
          description="Field evidence focuses the check on what matters right now."
        >
        <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <span className={label}>Latest scouting concern</span>
            <input className={input} value={concern.text} onChange={(e) => setConcern((c) => ({ ...c, text: e.target.value }))} placeholder="gray mold on fruit, spreading" />
          </div>
          <div>
            <span className={label}>Severity (1–5)</span>
            <select className={input} value={concern.severity} onChange={(e) => setConcern((c) => ({ ...c, severity: e.target.value }))}>
              <option value="">—</option>
              {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        </section>
        </SectionCard>

        <FormError>{error}</FormError>
        <div className="flex items-center gap-2">
          <Button type="submit" disabled={saving}>
            {saving ? "Creating…" : "Create pilot farm"}
          </Button>
          <Link href="/farms">
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </Link>
        </div>
      </form>
    </div>
  );
}
