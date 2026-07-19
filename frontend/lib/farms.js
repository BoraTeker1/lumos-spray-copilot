// Shared farm-visibility rule. The YC demo is the California strawberry / PCA
// workflow only: secondary-market demo farms (Türkiye greenhouse tomatoes) never
// render in lists or the farm switcher — they stay seeded and reachable by
// direct URL, but there is deliberately no link or toggle to them. Real
// (non-demo) farms always show.
export function isSecondaryDemoFarm(f) {
  return f.is_demo && (f.country || "").toUpperCase() !== "US";
}

// Provenance tag for records created interactively on a demo farm. The backend
// rejects mixing real and simulated records on one farm (409), so anything added
// to a demo farm during a walkthrough is saved as what it truly is: simulated
// demo data (excluded from every real pilot metric). On real farms this is empty
// and the forms' own provenance stands.
export function demoProvenance(farm) {
  return farm?.is_demo
    ? { data_source: "demo", data_confidence: "simulated" }
    : {};
}
