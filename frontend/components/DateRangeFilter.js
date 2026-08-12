"use client";

import { Input } from "@/components/ui/input";

// From/to date inputs for client-side filtering of already-loaded rows.
// value = { from: "YYYY-MM-DD"|"", to: "YYYY-MM-DD"|"" }
export default function DateRangeFilter({ value, onChange }) {
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });
  return (
    <div className="flex items-center gap-1.5">
      <label className="sr-only" htmlFor="date-from">From date</label>
      <Input
        id="date-from"
        type="date"
        value={value.from}
        onChange={set("from")}
        className="h-9 w-36 text-xs"
        aria-label="From date"
      />
      <span className="text-xs text-muted">–</span>
      <label className="sr-only" htmlFor="date-to">To date</label>
      <Input
        id="date-to"
        type="date"
        value={value.to}
        onChange={set("to")}
        className="h-9 w-36 text-xs"
        aria-label="To date"
      />
    </div>
  );
}

// Shared predicate: does `dateStr` (YYYY-MM-DD) fall inside the range?
// Pure string comparison on ISO dates — no Date parsing, no timezone traps.
export function inDateRange(dateStr, range) {
  if (!dateStr) return !range.from && !range.to;
  if (range.from && dateStr < range.from) return false;
  if (range.to && dateStr > range.to) return false;
  return true;
}
