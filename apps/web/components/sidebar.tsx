"use client";

import {
  ChevronLeft,
  ChevronRight,
  Key,
  LogOut,
  ScrollText,
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
}

function NavItems({ collapsed }: NavItemsProps) {
  const pathname = usePathname();
  const isAdmin = useIsKeycloakAdmin();
  const isOpensearchAdmin = useIsOpensearchAdmin();
  const isPiiAdmin = useIsPiiAdmin();
  const currentUserId = useCurrentUserId();

  // Admin-only items
  const adminItems = isAdmin
    ? [
        { href: "/users", label: "Users", icon: Users },
        { href: "/clients", label: "Clients", icon: Key },
      ]
    : [];

  // Logs viewer (opensearch-admin role)
  const logsItems = isOpensearchAdmin
    ? [{ href: "/logs", label: "Logs", icon: ScrollText }]
    : [];

  // Personal items (always visible for authenticated users)
  const personalItems = currentUserId
    ? [
        {
          href: `/users/${currentUserId}`,
          label: "My Profile",
          icon: User,
        },
      ]
    : [];

  const mainItems = [
    ...(isPiiAdmin ? [{ href: "/policy-engine", label: "PII Policy", icon: Shield }] : []),
    ...logsItems,
    ...adminItems,
  ];

  const hasPersonalSection = personalItems.length > 0;

  return (
    <>
      {/* Main navigation */}
      <nav className="flex-1 space-y-1 p-2">
        {mainItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              }`}
            >
              <item.icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span className="hidden sm:inline">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Personal section */}
      {hasPersonalSection && (
        <div className="border-t border-sidebar-border p-2">
          {!collapsed && (
            <p className="hidden px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-sidebar-foreground/50 sm:block">
              Personal
            </p>
          )}
          {personalItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                }`}
              >
                <item.icon className="h-5 w-5 shrink-0" />
                {!collapsed && <span className="hidden sm:inline">{item.label}</span>}
              </Link>
            );
          })}
        </div>
      )}
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
  const auth = useAuth();

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
          onClick={() => { setCollapsed(!collapsed); }}
          className="ml-auto rounded-md p-1 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>

      <NavItems collapsed={collapsed} />

      {/* Log out */}
      <div className="border-t border-sidebar-border p-2">
        <button
          onClick={() => auth.signoutRedirect()}
          className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground transition-colors ${
            collapsed ? "justify-center px-0" : ""
          }`}
          aria-label="Log out"
        >
          <LogOut className="h-5 w-5 shrink-0" />
          {!collapsed && <span className="hidden sm:inline">Log out</span>}
        </button>
      </div>

      <VersionFooter collapsed={collapsed} />
    </aside>
  );
}
