"use client";

import { useEffect, useRef, useState } from "react";
import { KeyRound } from "lucide-react";
import { connectMcp, mcpError } from "@/lib/api/mcp";
import type { McpConnectionStatus } from "@/lib/api/mcp";

function isMcpOAuthCallback(
  event: MessageEvent<unknown>,
  popup: Window,
  callbackOrigin: string,
): boolean {
  if (event.origin !== callbackOrigin || event.source !== popup) return false;
  const data = event.data;
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    data.type === "oauth_callback" &&
    "status" in data &&
    (data.status === "success" || data.status === "error")
  );
}

export function McpConnection({
  id,
  status,
  onRefresh,
  appearance = "button",
  confirmReauthorize = false,
}: {
  id: string;
  status?: McpConnectionStatus["status"];
  onRefresh: () => void;
  appearance?: "button" | "link";
  confirmReauthorize?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const refresh = useRef(onRefresh);
  const active = useRef(true);
  const pending = useRef<{ popup: Window; callbackOrigin: string } | null>(null);

  function pendingFlow() {
    return pending.current;
  }

  useEffect(() => {
    refresh.current = onRefresh;
  }, [onRefresh]);

  useEffect(() => {
    active.current = true;
    const onMessage = (event: MessageEvent<unknown>) => {
      const flow = pending.current;
      if (!flow || !isMcpOAuthCallback(event, flow.popup, flow.callbackOrigin)) return;
      // Notification is only a hint. Always read the authenticated native status,
      // never trust a popup's status as proof of a stored connection.
      flow.popup.close();
      pending.current = null;
      setBusy(false);
      refresh.current();
    };
    window.addEventListener("message", onMessage);
    const interval = window.setInterval(() => {
      if (pending.current?.popup.closed) {
        pending.current = null;
        setBusy(false);
        refresh.current();
      }
    }, 1000);
    return () => {
      active.current = false;
      pending.current?.popup.close();
      pending.current = null;
      window.removeEventListener("message", onMessage);
      window.clearInterval(interval);
    };
  }, []);

  async function connect() {
    // Open synchronously in the click handler so browsers do not block the popup.
    const popup = window.open("about:blank", "_blank", "popup,width=600,height=750");
    if (!popup) {
      setError("Allow popups to connect your provider account.");
      return;
    }
    pending.current = { popup, callbackOrigin: "" };
    setBusy(true);
    setError("");
    try {
      const flow = await connectMcp(id);
      const current = pendingFlow();
      if (!active.current || current?.popup !== popup || popup.closed) {
        popup.close();
        return;
      }
      current.callbackOrigin = flow.callback_origin;
      popup.location.href = flow.authorization_url;
    } catch (error) {
      popup.close();
      if (active.current && pendingFlow()?.popup === popup) {
        pending.current = null;
        setBusy(false);
        setError(mcpError(error));
      }
    }
  }

  return (
    <div className={appearance === "link" ? "flex flex-col items-start gap-1" : "space-y-2"}>
      <div className={confirmReauthorize ? "flex flex-wrap justify-end gap-2" : ""}>
        {confirming && <button type="button" className="btn btn-sm btn-ghost" disabled={busy}
          onClick={() => { setConfirming(false); }}>
          Cancel
        </button>}
        <button
          type="button"
          className={appearance === "link"
            ? "link link-primary inline-flex h-4 items-center text-xs font-normal leading-4 disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
            : `btn btn-sm btn-outline${confirmReauthorize ? " w-36" : ""}`}
          disabled={busy}
          onClick={() => {
            if (confirmReauthorize && !confirming && (status === "connected" || status === "refresh pending")) {
              setConfirming(true);
            } else {
              setConfirming(false);
              void connect();
            }
          }}
        >
          {confirmReauthorize && appearance === "button" && <KeyRound className="h-4 w-4" aria-hidden />}
          {busy
            ? "Authorizing…"
            : confirming ? "Authorize"
            : status === "connected" || status === "refresh pending"
              ? "Reauthorize"
              : "Connect"}
        </button>
      </div>
      {error && (
        <p role="alert" className={appearance === "link" ? "max-w-xs text-xs text-error" : "max-w-xs text-sm text-error"}>
          {error}
        </p>
      )}
    </div>
  );
}
