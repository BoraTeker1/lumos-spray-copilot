"use client";

import { useEffect, useState } from "react";
import { KeyRound, ShieldAlert } from "lucide-react";
import { api, credentials } from "@/lib/api";
import { Button } from "@/components/ui/button";
import StatusBadge from "@/components/StatusBadge";
import { abstainReasonLabel } from "@/lib/status";

// Operator tooling for the Botrytis shadow pilot: issue PCA credentials, authorize
// them per farm, record the protocol, and read SHADOW risk assessments.
//
// This is the only surface in the app where an assessment is visible at all. The
// PCA-facing decision payload carries no risk field while the pilot is blinded, so
// this panel is not "the same data with a different layout" — it is the only view.
//
// Every call here needs the deployment's operator key. Without it the backend 403s,
// which is the point: these routes mint the credentials that make every other
// authorization guarantee meaningful.

export default function PilotOperatorCard({ farmId }) {
  const [operatorKey, setOperatorKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [creds, setCreds] = useState([]);
  const [issued, setIssued] = useState(null);
  const [assessments, setAssessments] = useState([]);
  const [protocols, setProtocols] = useState([]);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({
    display_name: "",
    license_identifier: "",
    license_state: "CA",
  });

  useEffect(() => {
    setHasKey(Boolean(credentials.getOperatorKey()));
  }, []);

  useEffect(() => {
    if (hasKey) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasKey, farmId]);

  async function load() {
    setError(null);
    try {
      const [credList, shadow] = await Promise.all([
        api.listPcaCredentials(),
        api.listShadowAssessments(farmId),
      ]);
      setCreds(credList);
      setAssessments(shadow);
      if (farmId) setProtocols(await api.listPilotProtocols(farmId));
    } catch (err) {
      setError(err.message);
    }
  }

  function saveKey(event) {
    event.preventDefault();
    if (!operatorKey.trim()) return;
    credentials.setOperatorKey(operatorKey.trim());
    setOperatorKey("");
    setHasKey(true);
  }

  async function issue(event) {
    event.preventDefault();
    setError(null);
    try {
      const created = await api.createPcaCredential({
        ...form,
        issued_by: "pilot-operator",
      });
      // The raw token is returned exactly once and is never retrievable again.
      setIssued(created);
      setForm({ display_name: "", license_identifier: "", license_state: "CA" });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function authorize(credentialId) {
    setError(null);
    try {
      await api.authorizePcaForFarm(credentialId, {
        farm_id: Number(farmId),
        granted_by: "pilot-operator",
      });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (!hasKey) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-gray-500" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-gray-900">Operator key required</h3>
        </div>
        <form onSubmit={saveKey} className="mt-3 space-y-2">
          <input
            type="password"
            value={operatorKey}
            onChange={(e) => setOperatorKey(e.target.value)}
            placeholder="LUMOS_OPERATOR_KEY"
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
          <p className="text-xs text-gray-500">
            Held for this browser session only. These routes issue PCA credentials, so
            leaving them open would let anyone reaching this API sign recommendations
            as an authorized advisor.
          </p>
          <Button type="submit" size="sm" disabled={!operatorKey.trim()}>
            Use this key
          </Button>
        </form>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {/* ------------------------------------------------------- credentials */}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">PCA credentials</h3>
        <p className="mt-1 text-xs text-gray-600">
          Lumos does not verify licences — it records the identifier the operator
          enters and attributes decisions to it.
        </p>

        <form onSubmit={issue} className="mt-3 grid gap-2 sm:grid-cols-3">
          <input
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            placeholder="Name"
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
          <input
            value={form.license_identifier}
            onChange={(e) =>
              setForm({ ...form, license_identifier: e.target.value })
            }
            placeholder="Licence no."
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
          <Button
            type="submit"
            size="sm"
            disabled={!form.display_name.trim() || !form.license_identifier.trim()}
          >
            Issue credential
          </Button>
        </form>

        {issued?.token && (
          <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3">
            <p className="text-xs font-semibold text-amber-900">
              Copy this token now — it is shown once and cannot be retrieved again.
            </p>
            <code className="mt-1 block break-all rounded bg-white p-2 text-xs">
              {issued.token}
            </code>
          </div>
        )}

        <ul className="mt-3 space-y-1.5">
          {creds.map((c) => (
            <li
              key={c.id}
              className="flex items-center justify-between gap-2 rounded border border-gray-200 p-2 text-sm"
            >
              <span>
                {c.display_name}{" "}
                <span className="text-xs text-gray-500">
                  ({c.license_identifier} · {c.token_prefix}…)
                </span>
                {c.revoked_at && (
                  <span className="ml-1 text-xs text-red-600">revoked</span>
                )}
              </span>
              <span className="flex gap-1">
                {farmId && !c.revoked_at && (
                  <Button size="sm" variant="outline" onClick={() => authorize(c.id)}>
                    Authorize for farm
                  </Button>
                )}
                {!c.revoked_at && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      await api.revokePcaCredential(c.id);
                      await load();
                    }}
                  >
                    Revoke
                  </Button>
                )}
              </span>
            </li>
          ))}
          {creds.length === 0 && (
            <li className="text-xs text-gray-500">No credentials issued yet.</li>
          )}
        </ul>
      </div>

      {/* ---------------------------------------------------------- protocol */}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Pilot protocol</h3>
        {protocols.length === 0 ? (
          <p className="mt-1 text-xs text-gray-500">
            No protocol recorded for this farm. Assessments stay in shadow mode until a
            protocol records an unblinding date — a farm without one can never drift
            out of shadow.
          </p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {protocols.map((p) => (
              <li key={p.id} className="rounded border border-gray-200 p-2 text-sm">
                <span className="font-medium">
                  {p.name} · {p.version}
                </span>
                <span className="ml-2 text-xs text-gray-500">
                  {p.assignment_method} · primary metric: {p.primary_metric}
                </span>
                <p className="mt-0.5 text-xs text-gray-500">
                  {p.unblinded_at
                    ? `Unblinded ${p.unblinded_at.slice(0, 10)}`
                    : "Blinded — the PCA sees no risk output"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ------------------------------------------------ shadow assessments */}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-gray-500" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-gray-900">
            Shadow risk assessments
          </h3>
        </div>
        <p className="mt-1 text-xs text-gray-600">
          Operator-only. These are absent from every PCA-facing payload, so the
          advisor&apos;s recorded decision stays an independent baseline.
          <strong className="ml-1 font-medium">
            Never quote these to the PCA during the pilot.
          </strong>
        </p>

        <ul className="mt-3 space-y-2">
          {assessments.map((a) => (
            <li key={a.id} className="rounded border border-gray-200 p-2 text-sm">
              <div className="flex items-center justify-between gap-2">
                <StatusBadge kind="riskBand" value={a.risk_band} />
                <span className="text-xs text-gray-500">
                  {a.model_version} · {a.computed_at?.slice(0, 16).replace("T", " ")}
                </span>
              </div>
              {a.abstained && (a.missing_inputs || []).length > 0 && (
                <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-gray-600">
                  {a.missing_inputs.map((reason) => (
                    <li key={reason}>{abstainReasonLabel(reason)}</li>
                  ))}
                </ul>
              )}
              <p className="mt-1 text-[11px] text-gray-500">
                {a.calibration_status} · {a.local_validation_status}
              </p>
            </li>
          ))}
          {assessments.length === 0 && (
            <li className="text-xs text-gray-500">
              No assessments computed yet.
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
