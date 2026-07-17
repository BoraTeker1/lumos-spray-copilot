import { Circle } from "lucide-react";
import { formatDate } from "@/lib/format";
import { orderEventLabel } from "@/lib/status";

// The append-only order event timeline, oldest first. Events are never edited
// or deleted — this renders the record exactly as it accumulated.
export default function OrderTimeline({ events = [] }) {
  if (!events.length) {
    return <p className="text-sm text-gray-500">No order events recorded yet.</p>;
  }
  return (
    <ol className="relative space-y-0 border-l border-gray-200 pl-5">
      {events.map((e) => (
        <li key={e.id} className="relative pb-4 last:pb-0">
          <span className="absolute -left-[27px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-gray-100 text-gray-600 ring-4 ring-white">
            <Circle className="h-2.5 w-2.5" />
          </span>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <span className="text-sm font-medium text-gray-900">
                {orderEventLabel(e.event_type)}
              </span>
              {e.actor && <span className="ml-2 text-xs text-gray-500">by {e.actor}</span>}
              {e.payload?.reason && (
                <div className="text-xs text-gray-600">Reason: {e.payload.reason}</div>
              )}
              {e.notes && <div className="text-xs text-gray-500">{e.notes}</div>}
            </div>
            <span className="shrink-0 text-xs text-gray-500">{formatDate(e.occurred_on)}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}
