import Breadcrumbs from "@/components/Breadcrumbs";

// Standard page header: breadcrumbs, 32/40 page title, meta line, actions slot.
//
// The title block is capped at 68ch and the row does NOT wrap: a long meta
// sentence used to push the actions onto a second line, which moved the primary
// CTA to a different place on every page. Actions stay top-right; the meta text
// wraps underneath instead.
export default function PageHeader({ breadcrumbs, title, meta, actions }) {
  return (
    <div className="border-b border-line pb-4">
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-title font-semibold text-ink">{title}</h1>
          {meta && (
            <div className="mt-1.5 flex max-w-[68ch] flex-wrap items-center gap-x-2 gap-y-1 text-body text-muted">
              {meta}
            </div>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
