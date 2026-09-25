"use client";

import {
  BarChart3,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  KeyRound,
  LogOut,
  ScrollText,
  Settings,
  Shield,
  User,
  Users,
} from "lucide-react";
import { useAuth } from "react-oidc-context";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { VersionInfo } from "@/lib/api/version";
import { fetchVersion } from "@/lib/api/version";
import {
  useCurrentUserId,
  useIsKeycloakAdmin,
  useIsOpensearchAdmin,
  useIsPiiAdmin,
} from "@/lib/auth/roles";

interface NavItemsProps {
  collapsed: boolean;
  onExpand: () => void;
}

function NavItems({ collapsed, onExpand }: NavItemsProps) {
  const pathname = usePathname();
  const auth = useAuth();
  const isAdmin = useIsKeycloakAdmin();
  const isOpensearchAdmin = useIsOpensearchAdmin();
  const isPiiAdmin = useIsPiiAdmin();
  const currentUserId = useCurrentUserId();
  const [configurationOpen, setConfigurationOpen] = useState(pathname === "/policy-engine");

  return (
    <>
      {/* Main navigation */}
      <nav className="flex-1 space-y-1 p-2">
        <Link
          href="/usage"
          className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
            pathname === "/usage"
              ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
              : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
          }`}
        >
          <BarChart3 className="h-5 w-5 shrink-0" />
          {!collapsed && <span className="hidden sm:inline">Usage</span>}
        </Link>
        {!isAdmin && !isOpensearchAdmin && (
          <span
            aria-disabled="true"
            title="API Keys (coming soon)"
            className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground/40"
          >
            <KeyRound className="h-5 w-5 shrink-0" />
            {!collapsed && <span className="hidden sm:inline">API Keys</span>}
          </span>
        )}
        {isAdmin && (
          <Link
            href="/users"
            className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
              pathname === "/users"
                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            }`}
          >
            <Users className="h-5 w-5 shrink-0" />
            {!collapsed && <span className="hidden sm:inline">Users</span>}
          </Link>
        )}
        {isOpensearchAdmin && (
          <Link
            href="/logs"
            className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
              pathname === "/logs"
                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            }`}
          >
            <ScrollText className="h-5 w-5 shrink-0" />
            {!collapsed && <span className="hidden sm:inline">Logs</span>}
          </Link>
        )}
      </nav>

      {/* Settings */}
      <div className="border-t border-sidebar-border p-2">
        {!collapsed && (
          <p className="hidden px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-sidebar-foreground/50 sm:block">
            Settings
          </p>
        )}
        {currentUserId && (
          <Link
            href={`/users/${currentUserId}`}
            aria-label="Profile"
            className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
              pathname === `/users/${currentUserId}`
                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            }`}
          >
            <User className="h-5 w-5 shrink-0" />
            {!collapsed && <span className="hidden sm:inline">Profile</span>}
          </Link>
        )}
        {isPiiAdmin && (
          <>
            <button
              type="button"
              onClick={() => {
                if (collapsed) {
                  onExpand();
                  setConfigurationOpen(true);
                } else {
                  setConfigurationOpen(!configurationOpen);
                }
              }}
              aria-expanded={configurationOpen}
              aria-controls="sidebar-configuration"
              aria-label="Configuration"
              className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                pathname === "/policy-engine"
                  ? "text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              }`}
            >
              <Settings className="h-5 w-5 shrink-0" />
              {!collapsed && (
                <>
                  <span className="hidden flex-1 text-left sm:inline">Configuration</span>
                  {configurationOpen ? (
                    <ChevronDown className="hidden h-4 w-4 sm:block" />
                  ) : (
                    <ChevronRight className="hidden h-4 w-4 sm:block" />
                  )}
                </>
              )}
            </button>
            <div
              id="sidebar-configuration"
              hidden={!configurationOpen}
              className={collapsed ? "" : "sm:pl-5"}
            >
              <Link
                href="/policy-engine"
                aria-label="PII Policy"
                className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  pathname === "/policy-engine"
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                }`}
              >
                <Shield className="h-5 w-5 shrink-0" />
                {!collapsed && <span className="hidden sm:inline">PII Policy</span>}
              </Link>
            </div>
          </>
        )}
        <button
          type="button"
          onClick={() => auth.signoutRedirect()}
          className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
          aria-label="Logout"
        >
          <LogOut className="h-5 w-5 shrink-0" />
          {!collapsed && <span className="hidden sm:inline">Logout</span>}
        </button>
      </div>
    </>
  );
}

function VersionFooter({ collapsed }: { collapsed: boolean }) {
  const [version, setVersion] = useState<VersionInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchVersion()
      .then((v) => {
        if (!cancelled) setVersion(v);
      })
      .catch(() => {
        // Silently ignore — version is non-essential.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!version) return null;

  return (
    <div className="border-t border-sidebar-border p-2">
      <div
        className={`flex items-center text-[10px] text-sidebar-foreground/40 ${
          collapsed ? "justify-center" : "px-3"
        }`}
        title={`AI Stack Studio v${version.version}`}
      >
        {collapsed ? (
          <span className="font-mono">v{version.version.split(".")[0]}</span>
        ) : (
          <span className="hidden font-mono sm:inline">v{version.version}</span>
        )}
      </div>
    </div>
  );
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`flex flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-all duration-200 ${
        collapsed ? "w-16" : "w-16 sm:w-60"
      }`}
    >
      {/* Header */}
      <div className="flex h-14 items-center justify-between border-b border-sidebar-border px-4">
        {!collapsed && (
          <span className="hidden text-sm font-semibold tracking-tight sm:inline">
            AI Stack Studio
          </span>
        )}
        <button
          onClick={() => {
            setCollapsed(!collapsed);
          }}
          className="ml-auto rounded-md p-1 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      <NavItems collapsed={collapsed} onExpand={() => setCollapsed(false)} />

      <VersionFooter collapsed={collapsed} />
    </aside>
  );
}
