// Shared farm-visibility rule. The YC demo is the California strawberry / PCA
// workflow only: secondary-market demo farms (Türkiye greenhouse tomatoes) never
// render in lists or the farm switcher — they stay seeded and reachable by
// direct URL, but there is deliberately no link or toggle to them. Real
// (non-demo) farms always show.
export function isSecondaryDemoFarm(f) {
  return f.is_demo && (f.country || "").toUpperCase() !== "US";
}
