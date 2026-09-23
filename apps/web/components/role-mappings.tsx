import type { AdminRole, AdminRoleMappings } from "@/lib/api/admin";

export function RoleList({ roles }: { roles: AdminRole[] }) {
  if (!roles.length) return <p className="text-sm text-muted-foreground">None</p>;
  return (
    <div className="flex flex-wrap gap-2">
      {roles.map((role) => (
        <span
          key={role.id}
          className="rounded border border-border bg-muted px-2 py-1 font-mono text-xs"
          title={role.description || undefined}
        >
          {role.name}
          {role.composite ? " (composite)" : ""}
        </span>
      ))}
    </div>
  );
}

export function RoleMappings({ mappings }: { mappings: AdminRoleMappings }) {
  return (
    <div className="space-y-4">
      <div>
        <h4 className="mb-2 text-sm font-medium">Realm roles</h4>
        <RoleList roles={mappings.realm_roles} />
      </div>
      <div>
        <h4 className="mb-2 text-sm font-medium">Application roles</h4>
        {!mappings.clients.length && <p className="text-sm text-muted-foreground">None</p>}
        <div className="space-y-3">
          {mappings.clients.map((client) => (
            <div key={client.id}>
              <p className="mb-1 font-mono text-xs text-muted-foreground">{client.client_id}</p>
              <RoleList roles={client.roles} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
