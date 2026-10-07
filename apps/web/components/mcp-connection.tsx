"use client";

import { useEffect, useRef, useState } from "react";
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
}: {
  id: string;
  status?: McpConnectionStatus["status"];
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
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
    <div className="space-y-2">
      <button
        type="button"
        className="btn btn-sm btn-outline"
        disabled={busy}
        onClick={() => void connect()}
      >
        {busy
          ? "Connecting…"
          : status === "connected" || status === "refresh pending"
            ? "Reconnect"
            : "Connect"}
      </button>
      {error && (
        <p role="alert" className="max-w-xs text-xs text-error">
          {error}
        </p>
      )}
    </div>
  );
}
