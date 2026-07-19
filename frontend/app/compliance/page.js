import { redirect } from "next/navigation";

// Compliance merged into Evidence & compliance (see components/CompliancePanel.js);
// the old bookmarkable route keeps working.
export default function CompliancePage() {
  redirect("/evidence?tab=compliance");
}
