import { forwardRef } from "react";
import { cn } from "@/lib/utils";
import { fieldClass } from "@/components/ui/input";

export const Textarea = forwardRef(function Textarea({ className, ...props }, ref) {
  // h-auto: textareas size by rows, not the 40px control height.
  return <textarea ref={ref} className={cn(fieldClass, "h-auto", className)} {...props} />;
});
