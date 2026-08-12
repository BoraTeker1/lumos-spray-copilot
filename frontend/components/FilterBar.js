"use client";

import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import DateRangeFilter from "@/components/DateRangeFilter";

// One-row filter bar: status chips (counts MUST come from the same predicates
// that filter the rows), optional selects (children), search, and date range.
export function FilterChip({ label, count, selected, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 ${
        selected
          ? "bg-leaf-700 text-white"
          : "border border-line bg-surface text-muted hover:bg-canvas hover:text-ink"
      }`}
    >
      {label}
      {count != null && (
        <span className={`tabular ${selected ? "opacity-80" : "text-muted/70"}`}>
          {count}
        </span>
      )}
    </button>
  );
}

export default function FilterBar({ chips, search, dateRange, children, right }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      {chips?.map((chip) => (
        <FilterChip key={chip.key} {...chip} />
      ))}
      {children}
      {dateRange && <DateRangeFilter value={dateRange.value} onChange={dateRange.onChange} />}
      {search && (
        <div className="relative ml-auto w-48">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <Input
            value={search.value}
            onChange={(e) => search.onChange(e.target.value)}
            placeholder={search.placeholder || "Search"}
            className="h-9 pl-7 text-xs"
            aria-label={search.placeholder || "Search"}
          />
        </div>
      )}
      {right}
    </div>
  );
}
