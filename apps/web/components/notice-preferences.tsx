"use client";

import { useEffect, useState } from "react";
import {
  getNoticeOverrides, getNoticePreferences, saveNoticeOverrides, saveNoticePreferences,
} from "@/lib/api/notice-preferences";
import type { NoticeOverrides, NoticePreferences } from "@/lib/api/notice-preferences";

const fields: { name: keyof NoticePreferences; label: string }[] = [
  { name: "show_no_pii", label: "No sensitive data found" },
  { name: "show_pass", label: "Sensitive data passed by policy" },
  { name: "show_changes", label: "Sensitive data changed" },
  { name: "show_reroutes", label: "Request rerouted" },
  { name: "show_timing", label: "Analysis timing" },
];

export function NoticeSettings({ keyId }: { keyId?: string }) {
  const [values, setValues] = useState<NoticePreferences | NoticeOverrides | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    const load = keyId ? getNoticeOverrides(keyId) : getNoticePreferences();
    void load.then((result) => { if (active) setValues(result); })
      .catch(() => { if (active) setError("Unable to load notice settings."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [keyId]);

  async function save() {
    if (!values) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      if (keyId) await saveNoticeOverrides(keyId, values);
      else await saveNoticePreferences(values as NoticePreferences);
      setSaved(true);
    } catch {
      setError("Unable to save notice settings. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card mt-6 border border-border bg-card p-6">
      <h2 className="text-lg font-semibold">{keyId ? "API key notices" : "Notice display"}</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {keyId ? "Inherit uses your profile setting for this key." :
          "Choose which informational notices you see. Blocks and errors always appear."}
      </p>
      {loading && <p role="status" className="mt-3">Loading notice settings…</p>}
      {error && <p role="alert" className="mt-3 text-error">{error}</p>}
      {values && <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {fields.map(({ name, label }) => (
          <label key={name} className="flex items-center justify-between gap-3 text-sm">
            <span>{label}</span>
            <select className="select select-bordered select-sm" aria-label={label}
              value={values[name] === null ? "inherit" : values[name] ? "on" : "off"}
              onChange={(event) => {
                const value = event.target.value === "inherit" ? null : event.target.value === "on";
                setValues({ ...values, [name]: value });
                setSaved(false);
              }}>
              {keyId && <option value="inherit">Inherit</option>}
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
          </label>
        ))}
      </div>}
      {values && <div className="mt-4 flex items-center gap-3">
        <button type="button" className="btn btn-primary btn-sm" disabled={saving} onClick={() => { void save(); }}>
          {saving ? "Saving…" : "Save notices"}
        </button>
        {saved && <span role="status" className="text-sm">Saved.</span>}
      </div>}
    </section>
  );
}
