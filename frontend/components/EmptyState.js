import { tone } from "@/lib/tones";

// Deliberate empty state: what this is, why it's empty, and what to do next.
//
// `size="sm"` is the in-card variant. A table that has no rows yet sits INSIDE a
// card that already has a border and a title, so the full-size dashed panel
// produced a box-inside-a-box roughly 200px tall for one sentence. The small
// variant drops the dashed frame and the tinted icon disc and reads as a note.
export default function EmptyState({
  icon: Icon,
  title,
  description,
  cta,
  size = "default",
}) {
  if (size === "sm") {
    return (
      <div className="flex flex-col items-center gap-1 px-4 py-8 text-center">
        {Icon && <Icon className="h-5 w-5 text-muted" aria-hidden />}
        <div className="text-sm font-medium text-ink">{title}</div>
        {description && <p className="max-w-md text-meta text-muted">{description}</p>}
        {cta && <div className="mt-2">{cta}</div>}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-line bg-surface px-6 py-10 text-center">
      {Icon && (
        <span
          className={`flex h-10 w-10 items-center justify-center rounded-full ${
            tone("neutral").dot
          }`}
        >
          <Icon className="h-5 w-5" aria-hidden />
        </span>
      )}
      <div className="text-sm font-semibold text-ink">{title}</div>
      {description && <p className="max-w-md text-meta text-muted">{description}</p>}
      {cta && <div className="mt-2">{cta}</div>}
    </div>
  );
}
