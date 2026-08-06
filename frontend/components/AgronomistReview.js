"use client";

import { useState } from "react";
import { api } from "@/lib/api";

const STATUS_STYLES = {
  pending: "bg-draft-bg text-ink",
  approved: "bg-ok-bg text-ok-fg",
  rejected: "bg-risk-bg text-risk-fg",
  edited: "bg-info-bg text-info-fg",
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
  const statusCls = STATUS_STYLES[status] || "bg-draft-bg text-ink";

  return (
    <div className="mt-4 rounded-control border bg-surface/60 p-3">
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
              className="rounded bg-info-fg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
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
              className="rounded bg-leaf px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Approve
            </button>
            <button
              onClick={() => setEditing(true)}
              disabled={saving}
              className="rounded bg-info-fg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Edit recommendation
            </button>
            <button
              onClick={() => apply({ agronomist_status: "rejected" })}
              disabled={saving}
              className="rounded bg-risk-fg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
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

      {error && <p className="mt-2 text-sm text-risk-fg">{error}</p>}
      <p className="mt-2 text-xs text-muted">
        Only <span className="font-medium">approved</span> or{" "}
        <span className="font-medium">edited</span> guidance is shared with the grower in
        the weekly report.
      </p>
    </div>
  );
}
