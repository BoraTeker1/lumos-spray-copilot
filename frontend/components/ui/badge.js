import { cn } from "@/lib/utils";

// Status badge — soft-tinted pill. Green = verified positive states only;
// amber/red = actionable review states; blue = informational (PCA review,
// changed product); neutral/outline for everything else.
const VARIANTS = {
  neutral: "bg-gray-100 text-gray-600 ring-gray-200",
  green: "bg-leaf-50 text-leaf-700 ring-green-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  blue: "bg-blue-50 text-blue-700 ring-blue-200",
  outline: "bg-white text-gray-600 ring-gray-300",
};

export function Badge({ className, variant = "neutral", ...props }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset [&_svg]:size-3 [&_svg]:shrink-0",
        VARIANTS[variant],
        className
      )}
      {...props}
    />
  );
}
