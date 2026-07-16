import { cn } from "@/lib/utils";

// shadcn-style card pieces, compacted for a dense operational dashboard.
export function Card({ className, ...props }) {
  return (
    <div
      className={cn("rounded-[10px] border border-gray-200 bg-white shadow-sm", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }) {
  return <div className={cn("flex flex-col gap-1 p-4 pb-2", className)} {...props} />;
}

export function CardTitle({ className, ...props }) {
  return (
    <h3
      className={cn("flex items-center gap-2 text-sm font-semibold text-gray-900 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-gray-400", className)}
      {...props}
    />
  );
}

export function CardDescription({ className, ...props }) {
  return <p className={cn("text-xs text-gray-500", className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn("p-4 pt-2", className)} {...props} />;
}
