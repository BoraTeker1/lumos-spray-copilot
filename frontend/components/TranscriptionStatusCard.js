"use client";

import { useEffect, useState } from "react";
import { FileWarning } from "lucide-react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import DataTable from "@/components/DataTable";

// The operator worklist: which EMPTY source is blocking which layer, and what document
// would fill it.
//
// This is the most actionable card on /internal, because every finance, market and
// agronomy model in the system currently refuses for exactly one reason — nobody has
// transcribed its source. The blocker is a reading task, not a build task, and this is
// the surface that says so with the specific document named.
//
// `primary_source` is rendered VERBATIM from the server and must stay that way. It is
// the difference between "we don't know" and "here is exactly what someone must read",
// and summarising it here would destroy the only part that is actionable. The list is
// generated from the domain registry, so a domain admitted later appears automatically.
export default function TranscriptionStatusCard() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getTranscriptionStatus()
      .then((s) => !cancelled && setStatus(s))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <SectionCard title="Transcription worklist" icon={<FileWarning />} size="section">
        <p className="text-sm text-muted">Could not load: {error}</p>
      </SectionCard>
    );
  }
  if (!status) return null;

  return (
    <SectionCard
      title="Transcription worklist"
      icon={<FileWarning />}
      size="section"
      description={`${status.populated_count} of ${status.total_count} sources transcribed. Each empty source is a document someone must read — not code someone must write.`}
    >
      <DataTable
        columns={[
          {
            key: "module",
            header: "Source",
            render: (s) => (
              <code className="text-[11px]">{s.module.replace("app.", "")}</code>
            ),
          },
          {
            key: "state",
            header: "State",
            render: (s) => (
              <span className="text-xs font-medium text-muted">
                {s.populated ? `${s.row_count} entries` : "Empty"}
              </span>
            ),
          },
          {
            key: "primary_source",
            header: "What would fill it",
            priority: "secondary",
            // Verbatim. See the comment at the top of this file.
            render: (s) => <span className="text-xs text-muted">{s.primary_source}</span>,
          },
        ]}
        rows={status.sources}
        rowKey={(s) => s.module}
        minWidth={760}
      />
      <p className="mt-3 text-xs text-muted">{status.note}</p>
    </SectionCard>
  );
}
