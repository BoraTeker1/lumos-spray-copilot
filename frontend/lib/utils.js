import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// Merge Tailwind class lists (shadcn convention).
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
