"use client";

import { useState, useCallback } from "react";
import { Copy, Check, Code, ChevronDown } from "lucide-react";
import type { ConfigState } from "@/lib/config-generator";
import { generateYaml } from "@/lib/config-generator";

export function ConfigPreview({ state }: { state: ConfigState }) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(true);
  const yaml = generateYaml(state);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(yaml);
    setCopied(true);
    setTimeout(() => { setCopied(false); }, 2000);
  }, [yaml]);

  return (
    <div className="rounded-lg border border-border bg-muted/5 overflow-hidden">
      <button
        onClick={() => { setCollapsed(!collapsed); }}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-foreground hover:bg-muted/10 transition-colors"
      >
        <span className="flex items-center gap-2">
          <Code className="h-4 w-4 text-muted-foreground" />
          Generated Config
        </span>
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${collapsed ? "" : "rotate-180"}`} />
      </button>
      {!collapsed && (
        <div className="border-t border-border">
          <pre className="p-4 text-[11px] font-mono text-muted-foreground overflow-x-auto max-h-[500px] overflow-y-auto whitespace-pre">
            {yaml}
          </pre>
          <div className="flex justify-end px-4 pb-3">
            <button
              onClick={handleCopy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sidebar-primary px-4 py-2 text-sm font-medium text-sidebar-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {copied ? (
                <>
                  <Check className="h-3.5 w-3.5" /> Copied!
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" /> Copy to Clipboard
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
