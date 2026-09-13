import type { KeycloakUser } from "@/lib/api/admin";

export function UserStatus({ user }: { user: KeycloakUser }) {
  const enabled = user.enabled === true;
  const disabled = user.enabled === false;
  return (
    <div className="flex flex-wrap gap-1.5">
      <span
        className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${enabled ? "bg-green-100 text-green-800" : disabled ? "bg-red-100 text-red-800" : "bg-muted text-muted-foreground"}`}
      >
        {enabled ? "Enabled" : disabled ? "Disabled" : "Account status unknown"}
      </span>
      <span
        className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${user.email?.trim() && user.emailVerified === false ? "bg-amber-100 text-amber-800" : "bg-muted text-muted-foreground"}`}
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
