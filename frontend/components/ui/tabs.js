"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

// shadcn tabs converted to JS, underline style (Origin UI "with-line").
export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }) {
  return (
    <TabsPrimitive.List
      className={cn(
        "flex w-full items-center gap-5 overflow-x-auto border-b border-gray-200",
        className
      )}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 border-b-2 border-transparent pb-2 pt-1 text-sm font-medium text-gray-500 transition-colors hover:text-gray-800 focus-visible:outline-none data-[state=active]:border-gray-900 data-[state=active]:text-gray-900 [&_svg]:size-4",
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
