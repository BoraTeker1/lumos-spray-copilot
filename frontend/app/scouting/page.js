"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Eye, FlaskConical, Plus, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { severityLabel } from "@/lib/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import DataTable from "@/components/DataTable";
import DetailPanel, { DetailRow, DetailSection } from "@/components/DetailPanel";
import { inDateRange } from "@/components/DateRangeFilter";
import EmptyState from "@/components/EmptyState";
import FilterBar from "@/components/FilterBar";
import PageHeader from "@/components/PageHeader";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import SeverityBadge from "@/components/SeverityBadge";

const SEVERITY_FILTERS = [
  { key: "", label: "Any severity" },
  { key: "low", label: "Low (1–2)", match: (s) => s != null && s <= 2 },
  { key: "moderate", label: "Moderate (3)", match: (s) => s === 3 },
  { key: "high", label: "High (4–5)", match: (s) => s != null && s >= 4 },
];

// Presentation-only link: exact case-insensitive equality between the
// observation's issue and a decision's target. Never fuzzy — real target
// matching (aliases) lives in the backend engine.
function relatedDecision(observation, planned) {
  const issue = (observation.visible_issue || "").trim().toLowerCase();
  if (!issue) return null;
  return planned.find(
    (p) => (p.target_pest_or_disease || "").trim().toLowerCase() === issue
  );
}

// Two-line clamped notes with an accessible expand toggle.
function ClampedNotes({ text }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return <span className="text-muted">—</span>;
  return (
    <div className="max-w-[280px]">
      <p className={`text-xs text-muted ${expanded ? "" : "line-clamp-2"}`}>{text}</p>
      {text.length > 90 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-0.5 text-[11px] font-medium text-leaf-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        >
          {expanded ? "Show less" : "Expand"}
        </button>
      )}
    </div>
  );
}

export default function ScoutingPage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [observations, setObservations] = useState([]);
  const [planned, setPlanned] = useState([]);
  const [error, setError] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [fieldFilter, setFieldFilter] = useState("");
  const [issueFilter, setIssueFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [observerFilter, setObserverFilter] = useState("");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });
  const [selectedId, setSelectedId] = useState(null);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [o, p] = await Promise.all([
        api.listScoutObservations(farmId),
        api.listPlannedSprays(farmId),
      ]);
      setObservations(o);
      setPlanned(p);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => {
    const sev = SEVERITY_FILTERS.find((f) => f.key === severityFilter);
    return observations
      .filter(
        (o) =>
          (!fieldFilter || o.field_block === fieldFilter) &&
          (!issueFilter || o.visible_issue === issueFilter) &&
          (!sev?.match || sev.match(o.severity_1_to_5)) &&
          (!observerFilter || (o.observer || o.data_source || "") === observerFilter) &&
          inDateRange(o.observation_date, dateRange)
      )
      .sort((a, b) => (a.observation_date < b.observation_date ? 1 : -1));
  }, [observations, fieldFilter, issueFilter, severityFilter, observerFilter, dateRange]);

  // Selection follows the FILTERED rows: a row hidden by a filter must not keep
  // a stale panel open beside a table that no longer lists it.
  const selected = rows.find((o) => o.id === selectedId) || null;

  const fields = [...new Set(observations.map((o) => o.field_block).filter(Boolean))].sort();
  const issues = [...new Set(observations.map((o) => o.visible_issue).filter(Boolean))].sort();
  const observers = [
    ...new Set(observations.map((o) => o.observer || o.data_source).filter(Boolean)),
  ].sort();

  const columns = [
    {
      key: "date",
      header: "Date",
      render: (o) => (
        <span className="whitespace-nowrap text-ink">{formatDate(o.observation_date)}</span>
      ),
    },
    {
      key: "field",
      header: "Field",
      render: (o) => <span className="text-ink">{o.field_block || "—"}</span>,
    },
    {
      key: "issue",
      header: "Visible issue",
      render: (o) => <span className="font-medium text-ink">{o.visible_issue || "—"}</span>,
    },
    {
      key: "severity",
      header: "Severity",
      render: (o) => (
        <div className="flex items-center gap-1.5 whitespace-nowrap">
          <SeverityBadge value={o.severity_1_to_5} />
          <span className="text-xs text-muted">{severityLabel(o.severity_1_to_5)}</span>
        </div>
      ),
    },
    {
      key: "stage",
      header: "Crop stage",
      priority: "secondary",
      render: (o) => (
        <span className="capitalize text-ink">
          {o.crop_stage ? o.crop_stage.replace(/_/g, " ") : "—"}
        </span>
      ),
    },
    {
      key: "observer",
      header: "Observer / source",
      priority: "secondary",
      render: (o) => (
        <span className="text-xs text-muted">
          {(o.observer || o.data_source || "—").replace(/_/g, " ")}
        </span>
      ),
    },
    {
      key: "decision",
      header: "Related decision",
      priority: "secondary",
      render: (o) => {
        const match = relatedDecision(o, planned);
        return match ? (
          <Link
            href={`/decisions/${match.id}`}
            className="text-xs font-medium text-leaf-700 hover:underline"
          >
            {match.product_name}
          </Link>
        ) : (
          <span className="text-xs text-muted">—</span>
        );
      },
    },
    {
      key: "evidence",
      header: "Photos",
      priority: "secondary",
      render: (o) => (
        <span className="text-xs text-muted">{o.image_url_optional ? 1 : 0}</span>
      ),
    },
    {
      key: "notes",
      header: "Notes",
      render: (o) => <ClampedNotes text={o.notes} />,
    },
  ];

  if (farmsLoading) return <p className="text-sm text-muted">Loading…</p>;
  if (!activeFarm) {
    return (
      <p className="text-sm text-muted">
        No farms yet — seed the demo data or add a pilot farm first.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Scouting" }, { label: activeFarm.name }]}
        title="Scouting"
        meta={
          <span>
            Field observations for {activeFarm.name} — scouting evidence feeds the
            pre-spray decision checks.
          </span>
        }
        actions={
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus />
                Log scouting
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Log a scouting observation</DialogTitle>
                <DialogDescription>Date, visible issue, and severity 1–5.</DialogDescription>
              </DialogHeader>
              <ScoutObservationForm
                farmId={farmId}
                onCreated={async () => {
                  setDialogOpen(false);
                  await load();
                }}
              />
            </DialogContent>
          </Dialog>
        }
      />

      {error && (
        <div className="rounded-control border border-risk-line bg-risk-bg p-3 text-sm text-risk-fg">
          {error}
        </div>
      )}

      <div
        className={`grid grid-cols-1 gap-4 ${
          selected ? "2xl:grid-cols-[minmax(0,1fr)_340px]" : "grid-cols-1"
        }`}
      >
      <Card>
        <CardContent className="p-5">
          <FilterBar dateRange={{ value: dateRange, onChange: setDateRange }}>
            <Select
              value={fieldFilter}
              onChange={(e) => setFieldFilter(e.target.value)}
              className="h-9 w-auto text-xs"
              aria-label="Filter by field"
            >
              <option value="">All fields</option>
              {fields.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </Select>
            <Select
              value={issueFilter}
              onChange={(e) => setIssueFilter(e.target.value)}
              className="h-9 w-auto max-w-[200px] text-xs"
              aria-label="Filter by pest or disease"
            >
              <option value="">All pests / diseases</option>
              {issues.map((i) => (
                <option key={i} value={i}>{i}</option>
              ))}
            </Select>
            <Select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="h-9 w-auto text-xs"
              aria-label="Filter by severity"
            >
              {SEVERITY_FILTERS.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </Select>
            <Select
              value={observerFilter}
              onChange={(e) => setObserverFilter(e.target.value)}
              className="h-9 w-auto text-xs"
              aria-label="Filter by observer"
            >
              <option value="">All observers</option>
              {observers.map((o) => (
                <option key={o} value={o}>{o.replace(/_/g, " ")}</option>
              ))}
            </Select>
          </FilterBar>

          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(o) => o.id}
            minWidth={720}
            onRowClick={(o) => setSelectedId((cur) => (cur === o.id ? null : o.id))}
            selectedKey={selected?.id ?? null}
            empty={
              <EmptyState
                icon={Eye}
                title={
                  observations.length === 0
                    ? "No scouting observations yet"
                    : "Nothing matches these filters"
                }
                description={
                  observations.length === 0
                    ? "Log what you see in the field — severity and target evidence gate the pre-spray checks."
                    : "Clear a filter to see more observations."
                }
              />
            }
          />
        </CardContent>
      </Card>

      {/* Detail rail. Renders the row the table already has — no extra fetch,
          no derivation the table does not also perform. */}
      {selected && (
        <ObservationDetail
          observation={selected}
          decision={relatedDecision(selected, planned)}
          onClose={() => setSelectedId(null)}
        />
      )}
      </div>
    </div>
  );
}

function ObservationDetail({ observation: o, decision, onClose }) {
  return (
    <DetailPanel
      className="h-fit 2xl:sticky 2xl:top-20"
      title={o.visible_issue || "Observation"}
      subtitle={`${o.field_block ? `${o.field_block} · ` : ""}observed ${formatDate(
        o.observation_date
      )}`}
      badges={
        <>
          <SeverityBadge value={o.severity_1_to_5} />
          {(o.data_source === "demo" || o.data_confidence === "simulated") && (
            <Badge variant="outline">
              <FlaskConical />
              Simulated demo
            </Badge>
          )}
        </>
      }
      onClose={onClose}
      footer={
        decision ? (
          <Link href={`/decisions/${decision.id}`}>
            <Button className="w-full">
              <ShieldCheck />
              View related decision
            </Button>
          </Link>
        ) : (
          <p className="text-meta text-muted">
            No planned-spray decision names this exact target. Matching here is exact —
            the engine&apos;s alias matching is separate and stricter.
          </p>
        )
      }
    >
      <DetailSection title="Observation">
        <DetailRow label="Description" value={o.visible_issue} />
        <DetailRow label="Severity" value={severityLabel(o.severity_1_to_5)} />
        <DetailRow
          label="Crop stage"
          value={o.crop_stage ? o.crop_stage.replace(/_/g, " ") : null}
        />
        <DetailRow label="Field / block" value={o.field_block} />
        {o.notes && <p className="mt-2 text-sm text-muted">{o.notes}</p>}
      </DetailSection>
      <DetailSection title="Provenance">
        <DetailRow label="Record type" value="Scouting observation" />
        <DetailRow
          label="Data origin"
          value={(o.data_source || "—").replace(/_/g, " ")}
        />
        <DetailRow
          label="Confidence"
          value={(o.data_confidence || "—").replace(/_/g, " ")}
        />
        <DetailRow label="Observer" value={o.observer} />
        <DetailRow label="Observed on" value={formatDate(o.observation_date)} />
      </DetailSection>
    </DetailPanel>
  );
}
