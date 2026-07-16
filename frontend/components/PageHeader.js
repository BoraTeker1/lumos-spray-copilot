import Breadcrumbs from "@/components/Breadcrumbs";

// Standard page header: breadcrumbs, 28px title, meta line, actions slot.
export default function PageHeader({ breadcrumbs, title, meta, actions }) {
  return (
    <div>
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold leading-9 tracking-tight text-gray-900">
            {title}
          </h1>
          {meta && (
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[13px] text-gray-500">
              {meta}
            </div>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
