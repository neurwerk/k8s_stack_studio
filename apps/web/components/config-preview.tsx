"use client";

import { useState } from "react";
import { Copy, Check, Code, ChevronDown } from "lucide-react";
import type { ConfigState } from "@/lib/config-generator";
import {
  generateAgentGatewayYaml,
  generateModelAttachmentYaml,
  generatePiiPolicyYaml,
} from "@/lib/config-generator";

export function ConfigPreview({ state }: { state: ConfigState }) {
  const [copied, setCopied] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  const outputs = [
    {
      id: "gateway",
      title: "AgentGateway values",
      path: "infrastructure/networking/agentgateway/values.yaml",
      yaml: generateAgentGatewayYaml(state),
    },
    {
      id: "model",
      title: "Model attachment fields",
      path: "Merge into each intended existing model row",
      yaml: generateModelAttachmentYaml(state),
    },
    {
      id: "policy",
      title: "PII policy",
      path: "config/client.yaml",
      yaml: generatePiiPolicyYaml(state),
    },
  ];

  const handleCopy = async (id: string, yaml: string) => {
    await navigator.clipboard.writeText(yaml);
    setCopied(id);
    setTimeout(() => { setCopied(null); }, 2000);
  };

  return (
    <div className="card overflow-hidden border border-border bg-card">
      <button
        onClick={() => { setCollapsed(!collapsed); }}
         className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-foreground hover:bg-muted transition-colors"
      >
        <span className="flex items-center gap-2">
          <Code className="h-4 w-4 text-muted-foreground" />
          Generated Config
        </span>
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${collapsed ? "" : "rotate-180"}`} />
      </button>
      {!collapsed && (
        <div className="space-y-4 border-t border-border p-4">
          <p className="text-xs text-muted-foreground">
            Helm replaces complete model lists. Merge the model fields into existing rows instead
            of replacing the list.
          </p>
          {outputs.map((output) => (
            <section key={output.id} className="overflow-hidden rounded border border-border">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/20 px-3 py-2">
                <div>
                  <h3 className="text-xs font-medium text-foreground">{output.title}</h3>
                  <p className="text-[10px] text-muted-foreground">{output.path}</p>
                </div>
                <button
                  onClick={() => { void handleCopy(output.id, output.yaml); }}
                   className="btn btn-outline btn-xs gap-1.5"
                >
                  {copied === output.id ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                  {copied === output.id ? "Copied" : "Copy"}
                </button>
              </div>
               <pre className="max-h-[320px] overflow-auto whitespace-pre bg-[var(--code-background)] p-3 font-mono text-xs text-[var(--code-foreground)]">
                {output.yaml}
              </pre>
            </section>
          ))}
          </div>
      )}
    </div>
  );
}
