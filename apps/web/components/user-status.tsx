import type { KeycloakUser } from "@/lib/api/admin";

export function UserStatus({ user }: { user: KeycloakUser }) {
  const enabled = user.enabled === true;
  const disabled = user.enabled === false;
  return (
    <div className="flex flex-wrap gap-1.5">
      <span
        className={`badge badge-sm font-medium ${enabled ? "badge-success badge-outline" : disabled ? "badge-error badge-outline" : "badge-ghost"}`}
      >
        {enabled ? "Enabled" : disabled ? "Disabled" : "Account status unknown"}
      </span>
      <span
        className={`badge badge-sm font-medium ${user.email?.trim() && user.emailVerified === false ? "badge-warning badge-outline" : "badge-ghost"}`}
      >
        {!user.email?.trim()
          ? "No email"
          : user.emailVerified === true
            ? "Email verified"
            : user.emailVerified === false
              ? "Email unverified"
              : "Email verification unknown"}
      </span>
    </div>
  );
}
