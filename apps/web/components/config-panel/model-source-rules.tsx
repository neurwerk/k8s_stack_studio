"use client";

import { useState } from "react";
import type { EntityPolicyEntry } from "@/lib/config-generator";
import { EntityRow } from "./entity-row";

export function ModelSourceRules({ policies, defaultTarget, onChange }: {
  policies: Record<string, EntityPolicyEntry[]>;
  defaultTarget: string;
  onChange: (policies: Record<string, EntityPolicyEntry[]>) => void;
}) {
  const [model, setModel] = useState("");
  const validModel = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$/.test(model) && !Object.hasOwn(policies, model);
  return <div className="space-y-3">
    <p className="text-xs text-muted-foreground">Exact canonical model IDs only. Precedence: model source → model DEFAULT → global source → global DEFAULT → block. Empty model rules inherit global rules. Pass leaves text, safety and attachment checks active.</p>
    {Object.entries(policies).map(([id, rules]) => <fieldset key={id} className="space-y-2 rounded border border-border p-3">
      <legend className="px-1 font-mono text-xs">{id}</legend>
      {!rules.length && <p className="text-xs text-muted-foreground">All sources inherit global rules.</p>}
      {rules.map((entry, index) => <EntityRow key={index} entry={entry} sourceRule defaultTarget={defaultTarget}
        usedNames={rules.filter((_, item) => item !== index).map((item) => item.entityType)}
        onChange={(next) => { onChange({ ...policies, [id]: rules.map((rule, item) => item === index ? next : rule) }); }}
        onRemove={() => { onChange({ ...policies, [id]: rules.filter((_, item) => item !== index) }); }} />)}
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-outline btn-xs" disabled={rules.length >= 64} onClick={() => {
          const used = new Set(rules.map((rule) => rule.entityType));
          let name = "MCP_TOOL_DEFAULT";
          let suffix = 1;
          while (used.has(name)) name = `MCP_TOOL_SOURCE_${String(suffix++)}`;
          onChange({ ...policies, [id]: [...rules, { entityType: name, action: "block", params: {}, patterns: [] }] });
        }}>Add model source rule</button>
        <button className="btn btn-ghost btn-xs" onClick={() => {
          onChange(Object.fromEntries(Object.entries(policies).filter(([key]) => key !== id)));
        }}>Remove model override</button>
      </div>
    </fieldset>)}
    <label className="block space-y-1 text-xs">Canonical model ID
      <input className="input input-bordered w-full font-mono text-sm" value={model} maxLength={128}
        aria-invalid={Boolean(model) && !validModel} onChange={(event) => { setModel(event.target.value); }} placeholder="provider/model-id" />
    </label>
    {model && !validModel && <p className="text-xs text-error">Use a unique ID starting with a letter or digit, followed by letters, digits, dots, underscores, slashes or hyphens.</p>}
    <button className="btn btn-outline btn-xs" disabled={!validModel || Object.keys(policies).length >= 256} onClick={() => {
      onChange({ ...policies, [model]: [] });
      setModel("");
    }}>Add explicit model</button>
  </div>;
}
