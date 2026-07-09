"use client";

import { useState } from "react";
import { api } from "@/lib/api";

// Fetches the plain-text weekly report and offers a one-click copy (for WhatsApp).
export default function WeeklyReport({ farmId }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.weeklyReport(farmId);
      setText(data.text);
      setCopied(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy to clipboard — select the text manually.");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end">
        <div className="flex gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            {loading ? "Loading…" : text ? "Refresh" : "Build report"}
          </button>
          {text && (
            <button
              onClick={copy}
              className="rounded bg-leaf px-3 py-1.5 text-sm font-medium text-white"
            >
              {copied ? "Copied" : "Copy for WhatsApp"}
            </button>
          )}
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {text && (
        <textarea
          readOnly
          value={text}
          rows={12}
          className="w-full rounded border bg-white p-3 font-mono text-xs"
        />
      )}
    </div>
  );
}
