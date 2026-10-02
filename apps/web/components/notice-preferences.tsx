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
  { name: "show_no_faces", label: "No faces found" },
  { name: "show_detected_faces", label: "Faces detected" },
  { name: "show_unscanned_faces", label: "Faces not scanned" },
];

export function inheritedNoticeOverrides(): NoticeOverrides {
  return {
    notices_enabled: null,
    ...Object.fromEntries(fields.map(({ name }) => [name, null])),
  } as NoticeOverrides;
}

export function NoticeControls({ values, profile, isKey, onChange }: {
  values: NoticePreferences | NoticeOverrides;
  profile: NoticePreferences | null;
  isKey: boolean;
  onChange: (next: NoticePreferences | NoticeOverrides) => void;
}) {
  const masterEnabled = values.notices_enabled ?? profile?.notices_enabled ?? true;

  function switchAll(enabled: boolean) {
    onChange({
      ...values,
      ...Object.fromEntries(fields.map(({ name }) => [name, enabled])),
      notices_enabled: enabled,
    });
  }

  function resetOverrides(name?: keyof NoticePreferences) {
    if (!isKey) return;
    onChange(name ? { ...values, [name]: null } : inheritedNoticeOverrides());
  }

  return <div className="mt-4 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/20 bg-accent/50 p-3">
      <div>
        <p className="text-sm font-semibold">Extra notices</p>
        <p className="text-xs text-muted-foreground">All categories</p>
      </div>
      <div className="flex items-center gap-3">
        {isKey && values.notices_enabled === null && (
          <span className="text-xs text-muted-foreground">Inherits profile</span>
        )}
        <span className="text-xs font-medium">{masterEnabled ? "On" : "Off"}</span>
        <input type="checkbox" className="toggle toggle-primary toggle-sm"
          aria-label="Extra notices (master)" checked={masterEnabled}
          onChange={(event) => { switchAll(event.target.checked); }} />
      </div>
    </div>
    {isKey && <button type="button" className="btn btn-ghost btn-xs" onClick={() => { resetOverrides(); }}>
      Use profile settings for this key
    </button>}
    <div className="ml-4 border-l-2 border-border pl-4 sm:ml-6 sm:pl-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Notice categories</p>
      <div className="grid gap-x-6 sm:grid-cols-2">
        {fields.map(({ name, label }) => {
          const enabled = masterEnabled && (values[name] ?? profile?.[name] ?? true);
          return (
            <div key={name} className="flex items-center justify-between gap-3 border-b border-border/70 py-2">
              <div className="min-w-0">
                <p className="text-sm">{label}</p>
                {isKey && values[name] === null && (
                  <p className="text-xs text-muted-foreground">Inherits profile</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {isKey && values[name] !== null && (
                  <button type="button" className="btn btn-ghost btn-xs" disabled={!masterEnabled}
                    onClick={() => { resetOverrides(name); }}>Inherit</button>
                )}
                <span className="text-xs font-medium">{enabled ? "On" : "Off"}</span>
                <input type="checkbox" className="toggle toggle-primary toggle-sm"
                  aria-label={label} checked={enabled} disabled={!masterEnabled}
                  onChange={(event) => { onChange({ ...values, [name]: event.target.checked }); }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  </div>;
}

export function NoticeSettings({ keyId, asPage = false }: { keyId?: string; asPage?: boolean }) {
  const [values, setValues] = useState<NoticePreferences | NoticeOverrides | null>(null);
  const [profile, setProfile] = useState<NoticePreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    const load = keyId
      ? Promise.all([getNoticeOverrides(keyId), getNoticePreferences()]).then(([overrides, user]) => {
        if (active) setProfile(user);
        return overrides;
      })
      : getNoticePreferences();
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
      {asPage ? <h1 className="text-2xl font-semibold">Notice display</h1>
        : <h2 className="text-lg font-semibold">{keyId ? "API key notices" : "Notice display"}</h2>}
      <p className="mt-1 text-sm text-muted-foreground">
        {keyId
          ? "Override your profile's informational notices for this key; turning them off does not hide API errors or disable PII scanning."
          : "Choose which informational notices you see; turning them off does not hide API errors or disable PII scanning."}
      </p>
      {loading && <p role="status" className="mt-3">Loading notice settings…</p>}
      {error && <p role="alert" className="mt-3 text-error">{error}</p>}
      {values && <NoticeControls values={values} profile={profile} isKey={Boolean(keyId)}
        onChange={(next) => { setValues(next); setSaved(false); }} />}
      {values && <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
        {saved && <span role="status" className="text-sm text-muted-foreground">
          Saved. Changes may take up to 5 minutes to take effect.
        </span>}
        <button type="button" className="btn btn-primary btn-sm" disabled={saving} onClick={() => { void save(); }}>
          {saving ? "Saving…" : "Save notices"}
        </button>
      </div>}
    </section>
  );
}
