"use client";

import { useState } from "react";
import { api } from "@/lib/api";

const STATUS_STYLES = {
  pending: "bg-gray-100 text-gray-700",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  edited: "bg-indigo-100 text-indigo-800",
};

// Agronomist review controls for a single recommendation:
// Approve / Reject directly, or Edit the guidance text. A comment can be attached.
export default function AgronomistReview({ recommendation, onUpdated }) {
  const [comment, setComment] = useState(recommendation.agronomist_comment || "");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(recommendation.recommendation_text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function apply(payload) {
    setSaving(true);
    setError(null);
    try {
      await api.updateRecommendation(recommendation.id, {
        agronomist_comment: comment || null,
        ...payload,
      });
      setEditing(false);
      onUpdated && (await onUpdated());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const status = recommendation.agronomist_status;
  const statusCls = STATUS_STYLES[status] || "bg-gray-100 text-gray-700";

  return (
    <div className="mt-4 rounded-md border bg-white/60 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-medium">PCA / agronomist review</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusCls}`}>
          {status}
        </span>
      </div>

      {editing ? (
        <div className="space-y-2">
          <textarea
            className="w-full rounded border p-2 text-sm"
            rows={8}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              onClick={() => apply({ agronomist_status: "edited", recommendation_text: draft })}
              disabled={saving}
              className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Save edited guidance
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setDraft(recommendation.recommendation_text);
              }}
              className="rounded border px-3 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <textarea
            className="w-full rounded border p-2 text-sm"
            rows={2}
            placeholder="Add a PCA / agronomist comment (optional)…"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              onClick={() => apply({ agronomist_status: "approved" })}
              disabled={saving}
              className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Approve
            </button>
            <button
              onClick={() => setEditing(true)}
              disabled={saving}
              className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Edit recommendation
            </button>
            <button
              onClick={() => apply({ agronomist_status: "rejected" })}
              disabled={saving}
              className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Reject
            </button>
            {status !== "pending" && (
              <button
                onClick={() => apply({ agronomist_status: "pending" })}
                disabled={saving}
                className="rounded border px-3 py-1.5 text-sm"
              >
                Reset to pending
              </button>
            )}
          </div>
        </>
      )}

      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <p className="mt-2 text-xs text-gray-500">
        Only <span className="font-medium">approved</span> or{" "}
        <span className="font-medium">edited</span> guidance is shared with the grower in
        the weekly report.
      </p>
    </div>
  );
}
