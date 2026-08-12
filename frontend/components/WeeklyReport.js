"use client";

import { useState } from "react";
import { Check, Copy, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";

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
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : undefined} aria-hidden />
            {loading ? "Loading…" : text ? "Refresh" : "Build report"}
          </Button>
          {text && (
            <Button type="button" onClick={copy}>
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? "Copied" : "Copy for WhatsApp"}
            </Button>
          )}
        </div>
      </div>
      <FormError>{error}</FormError>
      {text && (
        <label className="block">
          <span className="sr-only">Weekly report text</span>
          <Textarea readOnly value={text} rows={12} className="p-3 font-mono text-xs" />
        </label>
      )}
    </div>
  );
}
