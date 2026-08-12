import { redirect } from "next/navigation";

// The lender-console version of this page is gone (2026-08-12).
//
// It was four read-only tables of assessments that all refused, aimed at a lender
// rather than at the §1 buyer, and unlinked from the nav since 2026-08-10. Financing
// now lives at /financing, farm-scoped and reached from the farm page — because the
// product argument is that financing is not a separate module, it is what a farm's
// operational record makes possible.
//
// The backend routes it read (`/farms/{id}/credit-assessments` and the rest) are
// untouched and still served; nothing was deleted, only re-homed. The old
// bookmarkable route keeps working.
export default function FinancePage() {
  redirect("/financing");
}
