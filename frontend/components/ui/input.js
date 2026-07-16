import { forwardRef } from "react";
import { cn } from "@/lib/utils";

// Shared form-control recipe — used by Input, Select, and Textarea so every
// form field in the app focuses green and rounds the same way.
export const fieldClass =
  "h-10 w-full rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 placeholder:text-gray-400 focus:border-leaf-600 focus:outline-none focus:ring-1 focus:ring-leaf-600 disabled:cursor-not-allowed disabled:bg-gray-50";

export const Input = forwardRef(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(fieldClass, className)} {...props} />;
});
