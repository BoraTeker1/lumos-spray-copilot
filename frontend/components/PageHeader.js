import Breadcrumbs from "@/components/Breadcrumbs";

// Standard page header: breadcrumbs, 32/40 page title, meta line, actions slot.
//
// The title block is capped at 68ch and, from `lg` up, the row does NOT wrap: a
// long meta sentence used to push the actions onto a second line, which moved
// the primary CTA to a different place on every page. Actions stay top-right and
// the meta text wraps underneath instead.
//
// Below `lg` it stacks. The threshold is `lg` rather than `sm` for the same
// reason the table tiers are one breakpoint high: the sidebar appears at `md`,
// so a 775px viewport leaves the header only ~445px, and holding the row
// together there squeezed the title to two words per line beside the buttons.
// The no-wrap rule exists to stabilise the CTA's position, not to survive any
// width at all.
export default function PageHeader({ breadcrumbs, title, meta, actions }) {
  return (
    <div className="border-b border-line pb-4">
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between lg:gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-title font-semibold text-ink">{title}</h1>
          {meta && (
            <div className="mt-1.5 flex max-w-[68ch] flex-wrap items-center gap-x-2 gap-y-1 text-body text-muted">
              {meta}
            </div>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
