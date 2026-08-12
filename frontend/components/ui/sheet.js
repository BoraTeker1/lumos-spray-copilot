"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// shadcn sheet (side panel) converted to JS, built on the same Radix dialog.
export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

const SIDES = {
  right: "inset-y-0 right-0 h-full w-full border-l border-line sm:max-w-lg",
  left: "inset-y-0 left-0 h-full w-72 border-r border-line",
};

// `padded` (default) keeps the historical single-scroll body. Pass
// padded={false} when the panel supplies its own SheetBody/SheetFooter, so a
// long form scrolls under a pinned action bar instead of pushing it off-screen.
export function SheetContent({
  className,
  side = "right",
  padded = true,
  children,
  ...props
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/40" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 flex flex-col bg-surface shadow-lg focus:outline-none",
          padded ? "overflow-y-auto p-5" : "overflow-hidden",
          SIDES[side],
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="absolute right-4 top-4 rounded-control p-1 text-muted transition-colors hover:bg-canvas hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2">
          <X className="h-4 w-4" />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function SheetHeader({ className, ...props }) {
  return <div className={cn("mb-3 flex flex-col gap-1 pr-8", className)} {...props} />;
}

// Header bar for a sheet using padded={false} — supplies its own padding and
// rule, since the body scrolls independently beneath it.
export function SheetHeaderBar({ className, ...props }) {
  return (
    <div
      className={cn("shrink-0 border-b border-line px-5 py-4 pr-12", className)}
      {...props}
    />
  );
}

export function SheetTitle({ className, ...props }) {
  return (
    <DialogPrimitive.Title
      className={cn("text-section font-semibold text-ink", className)}
      {...props}
    />
  );
}

export function SheetDescription({ className, ...props }) {
  return (
    <DialogPrimitive.Description
      className={cn("text-meta text-muted", className)}
      {...props}
    />
  );
}

// Scrolling body for a sheet using padded={false}.
export function SheetBody({ className, ...props }) {
  return <div className={cn("min-h-0 flex-1 overflow-y-auto p-5", className)} {...props} />;
}

// Pinned action bar. Stays visible while the body scrolls, so "Save" on a long
// form is never below the fold.
export function SheetFooter({ className, ...props }) {
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-end gap-2 border-t border-line bg-surface px-5 py-3",
        className
      )}
      {...props}
    />
  );
}
