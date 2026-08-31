/** @file PII Policy page - config panel, YAML preview, and model-free evaluation. */

"use client";

import { useRef, useState } from "react";
import { Shield, Settings2, ChevronDown, MessageSquare, Play, Loader2, XCircle } from "lucide-react";
import { PolicyTester, TEST_TEMPLATES, getTemplateGroups, buildRequest } from "@/components/policy-tester";
import { ConfigPanel } from "@/components/config-panel";
import { ConfigPreview } from "@/components/config-preview";
import { ActionsReference } from "@/components/actions-reference";
import type { ConfigState } from "@/lib/config-generator";
import { createDefaultState, toPolicyOverride } from "@/lib/config-generator";
import type { EvaluateResponse } from "@/lib/api/policy-engine";
import { policyEngineEvaluate } from "@/lib/api/policy-engine";
import { useIsPiiAdmin } from "@/lib/auth/roles";

const DEFAULT_TEXT =
  "Hello John Doe, my AWS key is AKIAIOSFODNN7EXAMPLE and my email is john@example.com";

export default function PolicyEnginePage() {
  const isPiiAdmin = useIsPiiAdmin();
  const [config, setConfig] = useState<ConfigState>(createDefaultState);
  const [showConfig, setShowConfig] = useState(false);
  const [useDraftPolicy, setUseDraftPolicy] = useState(false);
  const [testText, setTestText] = useState(DEFAULT_TEXT);
  const [template, setTemplate] = useState("");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<EvaluateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const evaluationId = useRef(0);

  if (!isPiiAdmin) {
    return <div className="mx-auto max-w-3xl px-8 py-12 text-sm text-muted-foreground">The `pii-admin` role is required to use PII policy tools.</div>;
  }

  const clearEvaluation = () => {
    evaluationId.current += 1;
    setResult(null);
    setError(null);
    setLoading(false);
  };

  const updateTestText = (value: string) => {
    setTestText(value);
    clearEvaluation();
  };

  const handleEvaluate = async () => {
    if (!testText.trim()) return;
    const requestId = ++evaluationId.current;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const req = buildRequest(testText);
      const policy = useDraftPolicy ? toPolicyOverride(config.piiEngine) : undefined;
      const res = await policyEngineEvaluate(req, policy);
      if (requestId === evaluationId.current) setResult(res);
    } catch {
      if (requestId === evaluationId.current) {
        setError("Unable to evaluate this request. Please try again.");
      }
    } finally {
      if (requestId === evaluationId.current) setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-8">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <Shield className="h-6 w-6 text-sidebar-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">PII Policy</h1>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Build your LLM policy, evaluate it against the shared PII Engine, then copy the generated
          YAML into your client repo.
        </p>
      </div>

      <div className="space-y-6">
        {/* ── Config Accordion ─────────────────────────────────────────── */}
        <div className="rounded-lg border border-border bg-muted/5 overflow-hidden">
          <div className="flex items-center">
            <button
              onClick={() => { setShowConfig(!showConfig); }}
              className="flex-1 flex items-center justify-between px-4 py-3 text-sm font-medium text-foreground hover:bg-muted/10 transition-colors"
            >
              <span className="flex items-center gap-2">
                <Settings2 className="h-4 w-4 text-muted-foreground" />
                Configure Policy
              </span>
              <ChevronDown
                className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${
                  showConfig ? "rotate-180" : ""
                }`}
              />
            </button>
          </div>
          <div
            className={`transition-all duration-300 ease-in-out overflow-y-auto ${
              showConfig ? "max-h-[600px] opacity-100" : "max-h-0 opacity-0"
            }`}
          >
            <div className="px-4 pb-4 border-t border-border">
              <div className="pt-4">
                <ConfigPanel
                  state={config}
                  onChange={(nextConfig) => {
                    setConfig(nextConfig);
                    clearEvaluation();
                  }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* ── PII Actions Reference ───────────────────────────────────── */}
        <ActionsReference />

        {/* ── YAML Preview ─────────────────────────────────────────────── */}
        <ConfigPreview state={config} />

        {/* ── User input ─────────────────────────────────────────────────── */}
        <div className="rounded-lg border border-border bg-muted/5 overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/20 border-b border-border">
            <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
              User input (e.g. LibreChat)
            </span>
          </div>
          <div className="px-4 py-3 space-y-3">
            <div className="flex items-center gap-2">
              <label htmlFor="policy-test-text" className="text-sm font-medium text-foreground">Test Text</label>
              <select
                value={template}
                onChange={(e) => {
                  const val = e.target.value;
                  setTemplate(val);
                  if (val && TEST_TEMPLATES[val]) {
                      updateTestText(TEST_TEMPLATES[val].text);
                  }
                }}
                className="rounded-lg border border-border bg-background px-4 py-2 text-sm text-muted-foreground focus:outline-none focus:ring-1 focus:ring-sidebar-primary"
              >
                <option value="">Examples...</option>
                {getTemplateGroups().map(({ group, keys }) => (
                  <optgroup key={group} label={group}>
                    {keys.map((key) => (
                      <option key={key} value={key}>
                        {key}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <textarea
              id="policy-test-text"
              value={testText}
              onChange={(e) => {
                  updateTestText(e.target.value);
                setTemplate("");
              }}
              rows={4}
              className="w-full rounded-lg border border-border bg-background px-4 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-sidebar-primary resize-y"
              placeholder="Enter text to test against the policy engine..."
            />
            {error && (
              <div className="rounded border border-red-500/30 bg-red-500/5 p-3 flex items-start gap-2" role="alert">
                <XCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                <span className="text-sm text-red-600">{error}</span>
              </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={useDraftPolicy}
                  onChange={(event) => {
                    setUseDraftPolicy(event.target.checked);
                    clearEvaluation();
                  }}
                  className="h-3.5 w-3.5 rounded border-border accent-sidebar-primary"
                />
                Evaluate with the draft policy shown above
              </label>
              <button
                onClick={() => { void handleEvaluate(); }}
                disabled={loading || !testText.trim()}
                aria-busy={loading}
                className="inline-flex items-center gap-2 rounded-lg bg-sidebar-primary px-4 py-2 text-sm font-medium text-sidebar-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50 shrink-0"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {loading ? "Evaluating..." : "Evaluate policy"}
              </button>
            </div>
            {loading && <p className="text-[11px] text-muted-foreground" role="status">Evaluating policy without calling a model...</p>}
          </div>
        </div>

        {/* ── Tester ───────────────────────────────────────────────────── */}
        <PolicyTester request={buildRequest(testText)} result={result} />
      </div>
    </div>
  );
}
