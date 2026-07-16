"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

// Shared operational table.
// columns: [{ key, header, render(row), align: "left"|"right", priority: "primary"|"secondary" }]
// - "secondary" columns hide below lg and move into an expandable per-row details
//   panel (accessible button), so critical columns (incl. the action column, always
//   last) are never silently clipped.
// - The wrapper owns overflow-x-auto as a deliberate, visible fallback only.
const HEADER_CLS =
  "px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";

export default function DataTable({ columns, rows, rowKey, empty, minWidth }) {
  const [expanded, setExpanded] = useState(() => new Set());
  const secondary = columns.filter((c) => c.priority === "secondary");
  const primary = columns.filter((c) => c.priority !== "secondary");
  const hasSecondary = secondary.length > 0;

  if (!rows.length) return empty || null;

  const toggle = (key) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const cellCls = (col) =>
    `px-3 py-3.5 align-top text-sm ${col.align === "right" ? "text-right" : ""}`;

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full" style={minWidth ? { minWidth } : undefined}>
        <thead>
          <tr className="border-b border-gray-200">
            {hasSecondary && <th className="w-8 lg:hidden" aria-label="Details" />}
            {primary.map((col) => (
              <th
                key={col.key}
                className={`${HEADER_CLS} ${col.align === "right" ? "text-right" : ""}`}
              >
                {col.header}
              </th>
            ))}
            {secondary.map((col) => (
              <th
                key={col.key}
                className={`${HEADER_CLS} hidden lg:table-cell ${
                  col.align === "right" ? "text-right" : ""
                }`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map((row) => {
            const key = rowKey(row);
            const isOpen = expanded.has(key);
            return (
              <Fragment key={key}>
                <tr>
                  {hasSecondary && (
                    <td className="px-1 py-3.5 lg:hidden">
                      <button
                        type="button"
                        onClick={() => toggle(key)}
                        aria-expanded={isOpen}
                        aria-label={isOpen ? "Hide details" : "Show details"}
                        className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                      >
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </button>
                    </td>
                  )}
                  {primary.map((col) => (
                    <td key={col.key} className={cellCls(col)}>
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
                  <tr className="lg:hidden">
                    <td />
                    <td colSpan={primary.length} className="px-3 pb-3.5">
                      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-md bg-gray-50 p-3 text-xs">
                        {secondary.map((col) => (
                          <div key={col.key}>
                            <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                              {col.header}
                            </dt>
                            <dd className="mt-0.5 text-gray-800">{col.render(row)}</dd>
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
