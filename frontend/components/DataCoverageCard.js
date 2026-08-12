"use client";

import { useState } from "react";
import { Check, Minus } from "lucide-react";
import { Button } from "@/components/ui/button";

// What data Lumos actually has for this farm, and what it does not.
//
// The honest answer to "what Big Data is behind this". A domain counts as CONNECTED
// only when records exist for THIS farm — declaring a domain is not building it, and
// a coverage list that counted declarations would be exactly the pretence this card
// exists to prevent. Seventeen domains are declared; most are empty for most farms,
// and saying so plainly is more useful than a full-looking grid.

function Row({ row }) {
  const Icon = row.connected ? Check : Minus;
  return (
    <li className="flex items-start gap-2 py-1.5">
      <Icon
        className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
          row.connected ? "text-ok-fg" : "text-muted"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span
            className={`text-sm ${row.connected ? "text-ink" : "text-muted"}`}
          >
            {row.label}
          </span>
          {row.connected && (
            <span className="text-xs text-muted">
              {row.record_count} record(s)
            </span>
          )}
        </div>
        {!row.connected && row.empty_source && (
          <div className="text-[11px] text-muted">
            Needs a source transcribed by Lumos before it can compute.
          </div>
        )}
      </div>
    </li>
  );
}

export default function DataCoverageCard({ coverage }) {
  const [showAll, setShowAll] = useState(false);
  if (!coverage?.length) return null;

  const connected = coverage.filter((r) => r.connected);
  const missing = coverage.filter((r) => !r.connected);
  const shown = showAll ? coverage : connected;

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        <span className="font-medium text-ink">
          {connected.length} of {coverage.length}
        </span>{" "}
        data domains carry records for this farm. The rest are declared but not
        connected — Lumos does not compute over data it does not have.
      </p>

      <ul className="divide-y divide-line">
        {shown.map((row) => (
          <Row key={row.key} row={row} />
        ))}
      </ul>

      {missing.length > 0 && (
        <Button variant="ghost" size="sm" onClick={() => setShowAll((v) => !v)}>
          {showAll
            ? "Show connected only"
            : `Show ${missing.length} not connected`}
        </Button>
      )}
    </div>
  );
}
