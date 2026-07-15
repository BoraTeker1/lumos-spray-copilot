import { forwardRef } from "react";
import { cn } from "@/lib/utils";
import { fieldClass } from "@/components/ui/input";

export const Textarea = forwardRef(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(fieldClass, className)} {...props} />;
});
