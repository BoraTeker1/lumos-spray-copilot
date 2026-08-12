import { tone } from "@/lib/tones";

// Thin progress bar. `ratio` must be a real derived ratio (0..1) of backend
// counts — never a made-up score.
export default function ProgressBar({ ratio, tone: toneName = "good", className = "" }) {
  const pct = Math.max(0, Math.min(1, Number(ratio) || 0)) * 100;
  const t = tone(toneName);
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-draft-bg ${className}`}>
      <div className={`h-full rounded-full ${t.bar}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
