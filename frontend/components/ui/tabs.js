"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

// shadcn tabs converted to JS.
//
// Two variants, because this app nests one tab set inside another and giving
// both the same underline made two different levels of hierarchy look
// identical (on /evidence, "Evidence | Compliance" sat directly above
// "Pilot demo | Real operations" in the same style, reading as four peers).
//   * "underline" (default) — the page-level view switch.
//   * "segmented" — an enclosed pill group for a scope/filter switch NESTED
//     inside a view. It reads as a control, not as navigation.
export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, variant = "underline", ...props }) {
  return (
    <TabsPrimitive.List
      className={cn(
        variant === "segmented"
          ? "inline-flex items-center gap-1 rounded-control border border-line bg-canvas p-1"
          : "flex w-full items-center gap-5 overflow-x-auto border-b border-line",
        className
      )}
      {...props}
    />
  );
}

export function TabsTrigger({ className, variant = "underline", ...props }) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 text-sm font-medium text-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 [&_svg]:size-4",
        variant === "segmented"
          ? "rounded-[4px] px-3 py-1.5 hover:text-ink data-[state=active]:bg-surface data-[state=active]:text-ink data-[state=active]:shadow-sm"
          : "border-b-2 border-transparent pb-2 pt-1 hover:text-ink data-[state=active]:border-leaf-600 data-[state=active]:text-leaf-700",
        className
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }) {
  return (
    <TabsPrimitive.Content
      className={cn("mt-4 focus-visible:outline-none", className)}
      {...props}
    />
  );
}
