"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

// Shared operational table.
// columns: [{ key, header, render(row), align: "left"|"right", priority: "primary"|"secondary" }]
// - "secondary" columns hide below lg and move into an expandable per-row details
//   panel (accessible button), so critical columns (incl. the action column, always
//   last) are never silently clipped.
// - The wrapper owns overflow-x-auto as a deliberate, visible fallback only.
//
// Row selection is OPT-IN via `onRowClick`. A table without it renders no hover
// or selected affordance at all — a static record table must never look
// clickable, because a row that appears interactive and does nothing reads as a
// broken app.
const HEADER_CLS =
  "bg-surface px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted";

export default function DataTable({
  columns,
  rows,
  rowKey,
  empty,
  minWidth,
  onRowClick,
  selectedKey,
  stickyHeader = true,
}) {
  const [expanded, setExpanded] = useState(() => new Set());
  const secondary = columns.filter((c) => c.priority === "secondary");
  const primary = columns.filter((c) => c.priority !== "secondary");
  const hasSecondary = secondary.length > 0;
  const interactive = typeof onRowClick === "function";

  if (!rows.length) return empty || null;

  const toggle = (key) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const cellCls = (col) =>
    `px-3 py-3.5 align-top text-sm ${col.align === "right" ? "text-right tabular" : ""}`;

  const headCls = (col) =>
    `${HEADER_CLS} ${stickyHeader ? "sticky top-0 z-10" : ""} ${
      col.align === "right" ? "text-right" : ""
    }`;

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-separate border-spacing-0" style={minWidth ? { minWidth } : undefined}>
        <thead>
          <tr>
            {hasSecondary && (
              <th
                className={`w-8 border-b border-line lg:hidden ${
                  stickyHeader ? "sticky top-0 z-10 bg-surface" : ""
                }`}
                aria-label="Details"
              />
            )}
            {primary.map((col) => (
              <th key={col.key} className={`${headCls(col)} border-b border-line`}>
                {col.header}
              </th>
            ))}
            {secondary.map((col) => (
              <th
                key={col.key}
                className={`${headCls(col)} hidden border-b border-line lg:table-cell`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const isOpen = expanded.has(key);
            const isSelected = interactive && selectedKey != null && selectedKey === key;
            // The selected row gets a left accent bar AND a tint — the bar
            // survives when the tint is too subtle to see on a projector.
            const rowCls = [
              "border-b border-line/60",
              interactive &&
                "cursor-pointer transition-colors hover:bg-canvas focus-within:bg-canvas",
              isSelected && "bg-ok-bg/60",
            ]
              .filter(Boolean)
              .join(" ");
            const accentCls = isSelected
              ? "border-l-2 border-l-leaf-600"
              : interactive
                ? "border-l-2 border-l-transparent"
                : "";
            const rowProps = interactive
              ? {
                  onClick: () => onRowClick(row),
                  onKeyDown: (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onRowClick(row);
                    }
                  },
                  tabIndex: 0,
                  role: "button",
                  "aria-pressed": isSelected,
                }
              : {};
            return (
              <Fragment key={key}>
                <tr className={rowCls} {...rowProps}>
                  {hasSecondary && (
                    <td className={`px-1 py-3.5 lg:hidden ${accentCls}`}>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(key);
                        }}
                        aria-expanded={isOpen}
                        aria-label={isOpen ? "Hide details" : "Show details"}
                        className="rounded-control p-1 text-muted hover:bg-canvas hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-focus"
                      >
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </button>
                    </td>
                  )}
                  {primary.map((col, i) => (
                    <td
                      key={col.key}
                      className={`${cellCls(col)} ${
                        i === 0 && !hasSecondary ? accentCls : ""
                      }`}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                  {secondary.map((col) => (
                    <td key={col.key} className={`hidden lg:table-cell ${cellCls(col)}`}>
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
                {hasSecondary && isOpen && (
                  <tr className="border-b border-line/60 lg:hidden">
                    <td />
                    <td colSpan={primary.length} className="px-3 pb-3.5">
                      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-control bg-canvas p-3 text-xs">
                        {secondary.map((col) => (
                          <div key={col.key}>
                            <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                              {col.header}
                            </dt>
                            <dd className="mt-0.5 text-ink">{col.render(row)}</dd>
                          </div>
                        ))}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
