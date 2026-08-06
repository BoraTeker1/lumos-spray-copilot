import { cn } from "@/lib/utils";

// shadcn-style card pieces, compacted for a dense operational dashboard.
export function Card({ className, ...props }) {
  return (
    <div
      className={cn("rounded-card border border-line bg-surface shadow-sm", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }) {
  return <div className={cn("flex flex-col gap-1 p-4 pb-2", className)} {...props} />;
}

// `size="section"` is the 18/24 heading the design spec uses on major panels;
// the default stays the compact 14px title used inside dense cards.
export function CardTitle({ className, size = "default", ...props }) {
  return (
    <h3
      className={cn(
        "flex items-center gap-2 font-semibold text-ink [&_svg]:shrink-0 [&_svg]:text-muted",
        size === "section"
          ? "text-section [&_svg]:size-[18px]"
          : "text-sm [&_svg]:size-4",
        className
      )}
      {...props}
    />
  );
}

export function CardDescription({ className, ...props }) {
  return <p className={cn("text-meta text-muted", className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn("p-4 pt-2", className)} {...props} />;
}
