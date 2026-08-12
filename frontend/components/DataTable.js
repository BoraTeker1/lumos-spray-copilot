"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

// Shared operational table.
// columns: [{ key, header, render(row), align, priority, width, nowrap }]
// - align: "left" | "right"
// - priority: "primary" | "secondary" | "tertiary" | "action"
//   * "secondary" columns hide below xl and move into an expandable per-row
//     details panel (accessible button), so they are never silently clipped.
//     (Below xl rather than lg — see responsiveCls for why.)
//   * "tertiary" is the same idea one breakpoint later (hidden below 2xl). A
//     table with ten-plus columns cannot fit them all on a laptop: without a
//     third tier the only outcomes are a horizontal scrollbar on the primary
//     record table or every free-text cell wrapping to three lines. Reach for
//     it only for columns that are mostly "—" or that the detail rail repeats.
//   * "action" columns are PINNED LAST in DOM order, after the data columns,
//     and never collapse. Without this a page that declares its action column
//     in the middle of the list renders the button mid-table with data columns
//     trailing after it — which is exactly what every call site here used to
//     do, because an omitted priority fell through to "primary".
// - width: a CSS width, applied under table-layout:fixed, so a table's columns
//   are budgeted deliberately instead of being distributed by content length.
//   Long free-text cells otherwise steal width from short ones and every short
//   cell wraps. Omit widths entirely on a small table — auto layout sizes a
//   handful of columns to their content and cannot overflow a fixed cell.
// - nowrap: keep the cell on one line (dates, rates, badges).
// - The wrapper owns overflow-x-auto as a deliberate, visible fallback only.
//
// Row selection is OPT-IN via `onRowClick`. A table without it renders no hover
// or selected affordance at all — a static record table must never look
// clickable, because a row that appears interactive and does nothing reads as a
// broken app.
const HEADER_CLS =
  "bg-canvas px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted";

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
  const COLLAPSIBLE = ["secondary", "tertiary"];
  const secondary = columns.filter((c) => c.priority === "secondary");
  const tertiary = columns.filter((c) => c.priority === "tertiary");
  const action = columns.filter((c) => c.priority === "action");
  const primary = columns.filter(
    (c) => !COLLAPSIBLE.includes(c.priority) && c.priority !== "action"
  );
  // Everything that can drop out of the row must be recoverable from the
  // expander, or a filter/sort decision would be made on invisible data.
  const collapsible = [...secondary, ...tertiary];
  const hasSecondary = collapsible.length > 0;
  const interactive = typeof onRowClick === "function";
  // Render order is the visual order: primary, then collapsible, then actions.
  const ordered = [...primary, ...collapsible, ...action];

  if (!rows.length) return empty || null;

  const toggle = (key) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // Secondary columns collapse below xl, tertiary below 2xl; nothing else does.
  // Written as literals so Tailwind's content scanner emits both class pairs.
  //
  // These are one breakpoint higher than they look like they should be, on
  // purpose: the app always renders a ~250px sidebar, so at viewport 1024 the
  // table's container is only ~940px. Keyed off `lg` the secondary columns
  // reappeared before there was room for them and pushed the pinned action
  // column off the right edge.
  const responsiveCls = (col) =>
    col.priority === "secondary"
      ? "hidden xl:table-cell"
      : col.priority === "tertiary"
        ? "hidden 2xl:table-cell"
        : "";

  const cellCls = (col) =>
    [
      "px-3 py-3 align-middle text-sm",
      col.align === "right" ? "text-right tabular" : "",
      col.nowrap || col.priority === "action" ? "whitespace-nowrap" : "",
      responsiveCls(col),
    ]
      .filter(Boolean)
      .join(" ");

  // Headers WRAP; cells honour their column's own `nowrap`. Under table-fixed a
  // nowrap header longer than its budgeted column has nowhere to go and clips
  // mid-word — which is how "Source authority" came to render as
  // "SOURCE AUTHORI". A two-line header is the honest outcome.
  const headCls = (col) =>
    [
      HEADER_CLS,
      "border-y border-line align-bottom",
      stickyHeader ? "sticky top-0 z-10" : "",
      col.align === "right" ? "text-right" : "",
      responsiveCls(col),
    ]
      .filter(Boolean)
      .join(" ");

  // Declared widths only bind under table-layout:fixed. They are applied to the
  // <th> rather than a <colgroup> on purpose: a hidden <col> does not reliably
  // drop its width, so a collapsed column would keep reserving space, while a
  // hidden <th> leaves fixed layout to redistribute the remainder correctly.
  const hasWidths = columns.some((c) => c.width);

  return (
    <div className="w-full overflow-x-auto">
      <table
        className={`w-full border-separate border-spacing-0 ${
          hasWidths ? "table-fixed" : ""
        }`}
        style={minWidth ? { minWidth } : undefined}
      >
        <thead>
          <tr>
            {hasSecondary && (
              <th
                className={`w-8 border-y border-line xl:hidden ${
                  stickyHeader ? "sticky top-0 z-10 bg-canvas" : ""
                }`}
                aria-label="Details"
              />
            )}
            {ordered.map((col) => (
              <th
                key={col.key}
                className={headCls(col)}
                style={col.width ? { width: col.width } : undefined}
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
                    <td className={`px-1 py-3 xl:hidden ${accentCls}`}>
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
                  {ordered.map((col, i) => (
                    <td
                      key={col.key}
                      className={`${cellCls(col)} ${
                        i === 0 && !hasSecondary ? accentCls : ""
                      }`}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
                {hasSecondary && isOpen && (
                  <tr className="border-b border-line/60 xl:hidden">
                    <td />
                    <td colSpan={primary.length + action.length} className="px-3 pb-3.5">
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
