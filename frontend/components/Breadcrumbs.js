import Link from "next/link";

// Page-level breadcrumbs (rendered by each page as its first element, not by
// the shell). items: [{ label, href? }] — the last item is the current page.
export default function Breadcrumbs({ items = [] }) {
  if (!items.length) return null;
  return (
    <nav aria-label="Breadcrumb" className="no-print mb-3 text-meta text-muted">
      <ol className="flex flex-wrap items-center gap-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-line">/</span>}
            {item.href ? (
              <Link
                href={item.href}
                className="rounded-control hover:text-leaf-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2"
              >
                {item.label}
              </Link>
            ) : (
              <span className="font-medium text-ink">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
