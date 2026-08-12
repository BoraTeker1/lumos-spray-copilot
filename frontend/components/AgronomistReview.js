"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";

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
    <div className="mt-4 rounded-control border border-line bg-surface/60 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-medium">PCA / agronomist review</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusCls}`}>
          {status}
        </span>
      </div>

      {editing ? (
        <div className="space-y-2">
          <label className="block">
            <span className="sr-only">Edited guidance text</span>
            <Textarea rows={8} value={draft} onChange={(e) => setDraft(e.target.value)} />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              onClick={() => apply({ agronomist_status: "edited", recommendation_text: draft })}
              disabled={saving}
            >
              Save edited guidance
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setEditing(false);
                setDraft(recommendation.recommendation_text);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          <label className="block">
            <span className="sr-only">PCA / agronomist comment</span>
            <Textarea
              rows={2}
              placeholder="Add a PCA / agronomist comment (optional)…"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          {/* Approve is the only solid-filled action here. Reject was previously
              a solid red fill, which made the destructive control the loudest
              thing in the panel and out-ranked the approval it sits beside. */}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              type="button"
              onClick={() => apply({ agronomist_status: "approved" })}
              disabled={saving}
            >
              Approve
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setEditing(true)}
              disabled={saving}
            >
              Edit recommendation
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => apply({ agronomist_status: "rejected" })}
              disabled={saving}
            >
              Reject
            </Button>
            {status !== "pending" && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => apply({ agronomist_status: "pending" })}
                disabled={saving}
              >
                Reset to pending
              </Button>
            )}
          </div>
        </>
      )}

      <FormError className="mt-2">{error}</FormError>
      <p className="mt-2 text-xs text-muted">
        Only <span className="font-medium">approved</span> or{" "}
        <span className="font-medium">edited</span> guidance is shared with the grower in
        the weekly report.
      </p>
    </div>
  );
}
