import { cn } from "@/lib/utils";

// Status badge. Green = verified positive states only; amber/red = actionable
// review states; neutral/outline for everything else.
const VARIANTS = {
  neutral: "bg-gray-100 text-gray-700 ring-gray-500/20",
  green: "bg-green-100 text-green-800 ring-green-600/20",
  amber: "bg-amber-100 text-amber-800 ring-amber-600/20",
  red: "bg-red-100 text-red-800 ring-red-600/20",
  indigo: "bg-indigo-100 text-indigo-800 ring-indigo-600/20",
  outline: "bg-white text-gray-600 ring-gray-300",
};

export function Badge({ className, variant = "neutral", ...props }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset [&_svg]:size-3 [&_svg]:shrink-0",
        VARIANTS[variant],
        className
      )}
      {...props}
    />
  );
}
