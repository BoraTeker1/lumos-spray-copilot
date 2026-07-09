"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// shadcn sheet (side panel) converted to JS, built on the same Radix dialog.
export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

const SIDES = {
  right: "inset-y-0 right-0 h-full w-full border-l sm:max-w-lg",
  left: "inset-y-0 left-0 h-full w-72 border-r",
};

export function SheetContent({ className, side = "right", children, ...props }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 flex flex-col overflow-y-auto bg-white p-5 shadow-lg focus:outline-none",
          SIDES[side],
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm text-gray-400 hover:text-gray-700 focus:outline-none">
          <X className="h-4 w-4" />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function SheetHeader({ className, ...props }) {
  return <div className={cn("mb-3 flex flex-col gap-1 pr-6", className)} {...props} />;
}

export function SheetTitle({ className, ...props }) {
  return (
    <DialogPrimitive.Title
      className={cn("text-base font-semibold text-gray-900", className)}
      {...props}
    />
  );
}

export function SheetDescription({ className, ...props }) {
  return (
    <DialogPrimitive.Description
      className={cn("text-xs text-gray-500", className)}
      {...props}
    />
  );
}
