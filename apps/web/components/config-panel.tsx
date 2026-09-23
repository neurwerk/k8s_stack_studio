"use client";

import { Plus, Settings, Globe, Eye } from "lucide-react";

import type { AttachmentMode, AttachmentPolicyVersion, ConfigState, ImageForwarding } from "@/lib/config-generator";
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
  const updateGateway = (updates: Partial<ConfigState["llmPolicyEngine"]>) => onChange({ ...state, llmPolicyEngine: { ...state.llmPolicyEngine, ...updates } });
  const updateAttachment = (updates: Partial<ConfigState["llmPolicyEngine"]["attachment"]>) => updateGateway({ attachment: { ...state.llmPolicyEngine.attachment, ...updates } });
  const setAttachmentVersion = (version: AttachmentPolicyVersion) => {
    const attachment = { ...state.llmPolicyEngine.attachment };
    if (version === 1) {
      if (attachment.mode === "process") attachment.mode = "extract";
      attachment.imageForwarding = "none";
      attachment.faceProtectionEnabled = false;
      attachment.supportsImages = false;
    } else if (version === 2) {
      if (attachment.imageForwarding === "if-policy-allows") attachment.imageForwarding = "none";
      attachment.supportsImages = false;
    }
    onChange({ ...state, llmPolicyEngine: { ...state.llmPolicyEngine, attachmentPolicyVersion: version, attachment } });
  };
  const setAttachmentMode = (mode: AttachmentMode) => {
    if (mode === "passthrough") {
      updateAttachment({ mode, piiEnabled: false, imageForwarding: "none", faceProtectionEnabled: false, supportsImages: false });
    } else if (mode === "block") {
      updateAttachment({ mode, imageForwarding: "none", faceProtectionEnabled: false, supportsImages: false });
    } else {
      updateAttachment({ mode, faceProtectionEnabled: state.llmPolicyEngine.attachmentPolicyVersion > 1 });
    }
  };
  const setImageForwarding = (imageForwarding: ImageForwarding) => {
    if (imageForwarding === "if-no-pii-detected" || imageForwarding === "if-policy-allows") {
      updateAttachment({ imageForwarding, piiEnabled: true, faceProtectionEnabled: true });
    } else if (imageForwarding === "pii-unchecked") {
      updateAttachment({
        imageForwarding,
        faceProtectionEnabled: false,
        supportsImages: state.llmPolicyEngine.attachmentPolicyVersion === 3,
      });
    } else updateAttachment({ imageForwarding });
  };
  const usedTypes = new Set(engine.pii.entityPolicies.map((entry) => entry.entityType));
  const presets = PRESET_ENTITIES.filter((entity) => !usedTypes.has(entity));
  const attachment = state.llmPolicyEngine.attachment;
  const attachmentVersion = state.llmPolicyEngine.attachmentPolicyVersion;
  const processingAttachments = attachment.mode === "process" || attachment.mode === "extract";

  return <div className="space-y-5">
    <Section title="PII Engine Policy">
      <div className="flex flex-wrap items-center gap-2 text-[10px]"><Globe className="h-3.5 w-3.5" /><label>Languages</label><select multiple value={engine.pii.analyzerLanguages} onChange={(event) => updatePii({ analyzerLanguages: Array.from(event.target.selectedOptions, (option) => option.value) })}><option value="en">English</option><option value="de">German</option><option value="nl">Dutch</option></select><span>Default action</span><select value={engine.pii.defaultAction} onChange={(event) => updatePii({ defaultAction: event.target.value })}>{VALID_ACTIONS.filter((action) => action !== "reversible_replace").map((action) => <option key={action}>{action}</option>)}</select></div>
      <label className="flex items-center gap-2 text-[10px] text-muted-foreground"><input type="checkbox" checked={engine.pii.maskOnReroute} onChange={(event) => updatePii({ maskOnReroute: event.target.checked })} />Mask PII before local reroute</label>
      <label className="block text-[10px] text-muted-foreground">Score threshold: {engine.pii.scoreThreshold.toFixed(2)}<input className="block w-full" type="range" min="0" max="1" step="0.01" value={engine.pii.scoreThreshold} onChange={(event) => updatePii({ scoreThreshold: Number(event.target.value) })} /></label>
    </Section>

    <Section title="Attachments">
      <div className="grid gap-2 rounded border border-border bg-muted/20 p-2 text-[11px] sm:grid-cols-2">
        <label className="space-y-1">Contract version<select className="block w-full" value={attachmentVersion} onChange={(event) => setAttachmentVersion(Number(event.target.value) as AttachmentPolicyVersion)}><option value="1">1 - documents</option><option value="2">2 - image forwarding</option><option value="3">3 - face policy</option></select></label>
        <label className="space-y-1">Document handling<select className="block w-full" value={attachment.mode} onChange={(event) => setAttachmentMode(event.target.value as AttachmentMode)}><option value="block">Block attachments</option>{attachmentVersion > 1 && <option value="process">Process attachments</option>}<option value="extract">Extract text</option><option value="passthrough">Passthrough without inspection</option></select></label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={attachment.piiEnabled} disabled={attachment.mode === "passthrough"} onChange={(event) => updateAttachment({ piiEnabled: event.target.checked, imageForwarding: !event.target.checked && ["if-no-pii-detected", "if-policy-allows"].includes(attachment.imageForwarding) ? "none" : attachment.imageForwarding })} />Analyze extracted text for PII</label>
        {attachmentVersion > 1 && processingAttachments && <label className="flex items-center gap-2"><input type="checkbox" checked={attachment.faceProtectionEnabled} onChange={(event) => updateAttachment({ faceProtectionEnabled: event.target.checked, imageForwarding: !event.target.checked && ["if-no-pii-detected", "if-policy-allows"].includes(attachment.imageForwarding) ? "none" : attachment.imageForwarding })} />Protect faces</label>}
        {attachmentVersion > 1 && processingAttachments && <label className="space-y-1">Image forwarding<select className="block w-full" value={attachment.imageForwarding} onChange={(event) => setImageForwarding(event.target.value as ImageForwarding)}><option value="none">None - extracted text only</option><option value="if-no-pii-detected">Only when no PII is detected</option>{attachmentVersion === 3 && <option value="if-policy-allows">When policy allows</option>}<option value="pii-unchecked">Unchecked local model</option></select></label>}
        {attachmentVersion === 3 && processingAttachments && <label className="flex items-center gap-2"><input type="checkbox" checked={attachment.supportsImages} onChange={(event) => updateAttachment({ supportsImages: event.target.checked })} />Local model supports images</label>}
      </div>
      {attachment.mode === "passthrough" && <p className="text-[10px] text-amber-600">Passthrough sends raw attachments without PII or face inspection.</p>}
      {attachment.imageForwarding === "pii-unchecked" && <p className="text-[10px] text-amber-600">Unchecked forwarding also requires an existing concrete local model without PII rerouting.</p>}
      {attachmentVersion === 3 && <div className="grid gap-2 rounded border border-border p-2 text-[11px] sm:grid-cols-2"><label className="space-y-1">When a face is found<select className="block w-full" value={engine.attachments.faces.action} onChange={(event) => updateEngine({ attachments: { ...engine.attachments, faces: { ...engine.attachments.faces, action: event.target.value as ConfigState["piiEngine"]["attachments"]["faces"]["action"] } } })}><option value="block">Block</option><option value="text-only">Send extracted text only</option><option value="reroute">Reroute locally</option></select></label>{engine.attachments.faces.action === "reroute" && <label className="space-y-1">Route class (optional)<input className="block w-full" value={engine.attachments.faces.routeClass} onChange={(event) => updateEngine({ attachments: { ...engine.attachments, faces: { ...engine.attachments.faces, routeClass: event.target.value } } })} placeholder={engine.routing.defaultTarget} /></label>}</div>}
      <p className="text-[10px] text-muted-foreground">Attachment settings are generated as configuration only. The evaluator below remains text-only.</p>
    </Section>

    <Section title="Safety Rules"><div className="space-y-1 rounded border border-border bg-muted/20 p-2">{SAFETY_RULES.map((rule) => <label key={rule.id} className="flex items-center gap-2 text-[11px]"><input type="checkbox" checked={engine.safety.enabled.includes(rule.key)} onChange={(event) => updateEngine({ safety: { ...engine.safety, enabled: event.target.checked ? [...engine.safety.enabled, rule.key] : engine.safety.enabled.filter((key) => key !== rule.key) } })} />{rule.label}</label>)}</div>
      {engine.safety.custom.map((rule, index) => <SafetyRuleRow key={`${rule.name}-${index}`} rule={rule} onChange={(next) => { const custom = [...engine.safety.custom]; custom[index] = next; updateEngine({ safety: { ...engine.safety, custom } }); }} onRemove={() => updateEngine({ safety: { ...engine.safety, custom: engine.safety.custom.filter((_, item) => item !== index) } })} />)}
      <button className="inline-flex items-center gap-1 rounded border border-dashed px-2 py-1 text-[10px]" onClick={() => updateEngine({ safety: { ...engine.safety, custom: [...engine.safety.custom, { name: "customRule", pattern: "", action: "block", message: "Blocked by custom rule" }] } })}><Plus className="h-3 w-3" />Custom rule</button>
    </Section>

    <Section title="PII Entity Policies"><div className="space-y-2">{engine.pii.entityPolicies.map((entry, index) => <EntityRow key={`${entry.entityType}-${index}`} entry={entry} onChange={(next) => { const policies = [...engine.pii.entityPolicies]; policies[index] = next; updatePii({ entityPolicies: policies }); }} onRemove={() => updatePii({ entityPolicies: engine.pii.entityPolicies.filter((_, item) => item !== index) })} />)}</div>
      <div className="flex gap-2"><button className="inline-flex items-center gap-1 rounded border border-dashed px-2 py-1 text-[10px]" onClick={() => updatePii({ entityPolicies: [...engine.pii.entityPolicies, { entityType: "NEW_ENTITY", action: "replace", params: {}, patterns: [] }] })}><Plus className="h-3 w-3" />Custom entity</button><select value="" onChange={(event) => { if (event.target.value) updatePii({ entityPolicies: [...engine.pii.entityPolicies, { entityType: event.target.value, action: "replace", params: {}, patterns: [] }] }); }}><option value="">+ Add preset</option>{presets.map((entity) => <option key={entity}>{entity}</option>)}</select></div>
    </Section>

    <Section title="Classifier"><div className="flex items-center gap-2 text-[10px]"><Eye className="h-3.5 w-3.5" /><input value={engine.classifier.defaultClass} onChange={(event) => updateEngine({ classifier: { ...engine.classifier, defaultClass: event.target.value } })} /></div></Section>
    <Section title="Generated connection"><p className="text-[10px] text-muted-foreground">AgentGateway owns attachment handling per model. PII Engine owns face actions and text policy. The generated output keeps these separate.</p></Section>
  </div>;
}
