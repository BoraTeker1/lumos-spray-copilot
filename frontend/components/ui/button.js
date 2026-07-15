import { forwardRef } from "react";
import { cn } from "@/lib/utils";

// shadcn-style button, converted to plain JS. Solid dark green is reserved for
// the primary action ("default"); "secondary" is the outlined-green table/row
// action; everything else stays neutral.
const VARIANTS = {
  default: "bg-leaf-700 text-white shadow-sm hover:bg-leaf-800",
  secondary:
    "border border-leaf-600/40 bg-white text-leaf-700 shadow-sm hover:bg-leaf-50",
  outline:
    "border border-gray-300 bg-white text-gray-700 shadow-sm hover:bg-gray-50 hover:text-gray-900",
  ghost: "text-gray-600 hover:bg-gray-100 hover:text-gray-900",
  destructive: "border border-red-200 bg-white text-red-700 shadow-sm hover:bg-red-50",
};

const SIZES = {
  default: "h-9 px-4 py-2",
  sm: "h-8 rounded-lg px-3 text-xs",
  icon: "h-8 w-8",
};

export const Button = forwardRef(function Button(
  { className, variant = "default", size = "default", ...props },
  ref
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-leaf/40 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
        VARIANTS[variant],
        SIZES[size],
        className
      )}
      {...props}
    />
  );
});
