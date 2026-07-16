// Deliberate empty state: what this is, why it's empty, and what to do next.
export default function EmptyState({ icon: Icon, title, description, cta }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-[10px] border border-dashed border-gray-300 bg-white px-6 py-10 text-center">
      {Icon && (
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100 text-gray-500">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
      )}
      <div className="text-sm font-semibold text-gray-900">{title}</div>
      {description && <p className="max-w-md text-xs text-gray-500">{description}</p>}
      {cta && <div className="mt-2">{cta}</div>}
    </div>
  );
}
