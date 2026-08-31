"use client";

import { Plus, Settings, Globe, Eye } from "lucide-react";

import type { ConfigState } from "@/lib/config-generator";
import { PRESET_ENTITIES, SAFETY_RULES, VALID_ACTIONS } from "@/lib/config-generator";

import { EntityRow } from "./config-panel/entity-row";
import { SafetyRuleRow } from "./config-panel/safety-rule-row";

function Section({ title, children }: { title: string; children?: React.ReactNode }) {
  return <section className="space-y-2"><h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Settings className="h-3.5 w-3.5" />{title}</h2>{children}</section>;
}

export function ConfigPanel({ state, onChange }: { state: ConfigState; onChange: (state: ConfigState) => void }) {
  const engine = state.piiEngine;
  const updateEngine = (updates: Partial<ConfigState["piiEngine"]>) => onChange({ ...state, piiEngine: { ...engine, ...updates } });
  const updatePii = (updates: Partial<ConfigState["piiEngine"]["pii"]>) => updateEngine({ pii: { ...engine.pii, ...updates } });
  const usedTypes = new Set(engine.pii.entityPolicies.map((entry) => entry.entityType));
  const presets = PRESET_ENTITIES.filter((entity) => !usedTypes.has(entity));

  return <div className="space-y-5">
    <Section title="PII Engine Policy">
      <div className="flex flex-wrap items-center gap-2 text-[10px]"><Globe className="h-3.5 w-3.5" /><label>Languages</label><select multiple value={engine.pii.analyzerLanguages} onChange={(event) => updatePii({ analyzerLanguages: Array.from(event.target.selectedOptions, (option) => option.value) })}><option value="en">English</option><option value="de">German</option><option value="nl">Dutch</option></select><span>Default action</span><select value={engine.pii.defaultAction} onChange={(event) => updatePii({ defaultAction: event.target.value })}>{VALID_ACTIONS.filter((action) => action !== "reversible_replace").map((action) => <option key={action}>{action}</option>)}</select></div>
      <label className="flex items-center gap-2 text-[10px] text-muted-foreground"><input type="checkbox" checked={engine.pii.maskOnReroute} onChange={(event) => updatePii({ maskOnReroute: event.target.checked })} />Mask PII before local reroute</label>
      <label className="block text-[10px] text-muted-foreground">Score threshold: {engine.pii.scoreThreshold.toFixed(2)}<input className="block w-full" type="range" min="0" max="1" step="0.01" value={engine.pii.scoreThreshold} onChange={(event) => updatePii({ scoreThreshold: Number(event.target.value) })} /></label>
    </Section>

    <Section title="Safety Rules"><div className="space-y-1 rounded border border-border bg-muted/20 p-2">{SAFETY_RULES.map((rule) => <label key={rule.id} className="flex items-center gap-2 text-[11px]"><input type="checkbox" checked={engine.safety.enabled.includes(rule.key)} onChange={(event) => updateEngine({ safety: { ...engine.safety, enabled: event.target.checked ? [...engine.safety.enabled, rule.key] : engine.safety.enabled.filter((key) => key !== rule.key) } })} />{rule.label}</label>)}</div>
      {engine.safety.custom.map((rule, index) => <SafetyRuleRow key={`${rule.name}-${index}`} rule={rule} onChange={(next) => { const custom = [...engine.safety.custom]; custom[index] = next; updateEngine({ safety: { ...engine.safety, custom } }); }} onRemove={() => updateEngine({ safety: { ...engine.safety, custom: engine.safety.custom.filter((_, item) => item !== index) } })} />)}
      <button className="inline-flex items-center gap-1 rounded border border-dashed px-2 py-1 text-[10px]" onClick={() => updateEngine({ safety: { ...engine.safety, custom: [...engine.safety.custom, { name: "customRule", pattern: "", action: "block", message: "Blocked by custom rule" }] } })}><Plus className="h-3 w-3" />Custom rule</button>
    </Section>

    <Section title="PII Entity Policies"><div className="space-y-2">{engine.pii.entityPolicies.map((entry, index) => <EntityRow key={`${entry.entityType}-${index}`} entry={entry} onChange={(next) => { const policies = [...engine.pii.entityPolicies]; policies[index] = next; updatePii({ entityPolicies: policies }); }} onRemove={() => updatePii({ entityPolicies: engine.pii.entityPolicies.filter((_, item) => item !== index) })} />)}</div>
      <div className="flex gap-2"><button className="inline-flex items-center gap-1 rounded border border-dashed px-2 py-1 text-[10px]" onClick={() => updatePii({ entityPolicies: [...engine.pii.entityPolicies, { entityType: "NEW_ENTITY", action: "replace", params: {}, patterns: [] }] })}><Plus className="h-3 w-3" />Custom entity</button><select value="" onChange={(event) => { if (event.target.value) updatePii({ entityPolicies: [...engine.pii.entityPolicies, { entityType: event.target.value, action: "replace", params: {}, patterns: [] }] }); }}><option value="">+ Add preset</option>{presets.map((entity) => <option key={entity}>{entity}</option>)}</select></div>
    </Section>

    <Section title="Classifier"><div className="flex items-center gap-2 text-[10px]"><Eye className="h-3.5 w-3.5" /><input value={engine.classifier.defaultClass} onChange={(event) => updateEngine({ classifier: { ...engine.classifier, defaultClass: event.target.value } })} /></div></Section>
    <Section title="Generated connection"><p className="text-[10px] text-muted-foreground">PII Engine owns safety, entity actions, classification, and routing policy. Changes are emitted under <code>monitorPiiEngine</code>.</p></Section>
  </div>;
}
