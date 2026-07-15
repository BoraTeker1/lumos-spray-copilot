import { forwardRef } from "react";
import { cn } from "@/lib/utils";
import { fieldClass } from "@/components/ui/input";

export const Select = forwardRef(function Select({ className, ...props }, ref) {
  return <select ref={ref} className={cn(fieldClass, className)} {...props} />;
});
