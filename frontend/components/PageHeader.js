import Breadcrumbs from "@/components/Breadcrumbs";

// Standard page header: breadcrumbs, 32/40 page title, meta line, actions slot.
export default function PageHeader({ breadcrumbs, title, meta, actions }) {
  return (
    <div>
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-title font-semibold text-ink">{title}</h1>
          {meta && (
            <div className="mt-1 flex flex-wrap items-center gap-2 text-body text-muted">
              {meta}
            </div>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
