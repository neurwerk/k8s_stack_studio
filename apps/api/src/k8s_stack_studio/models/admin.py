"""Safe, read-only administration response models."""

from pydantic import BaseModel, ConfigDict


class AdminModel(BaseModel):
    """Reject accidental exposure of unmodeled Keycloak fields."""

    model_config = ConfigDict(extra="forbid")


class AdminRole(AdminModel):
    """Describe one safe realm or client role."""

    id: str
    name: str
    description: str = ""
    composite: bool = False


class AdminGroup(AdminModel):
    """Describe one group without attributes or access flags."""

    id: str
    name: str
    path: str
    subgroup_count: int = 0


class AdminClient(AdminModel):
    """Describe safe client metadata without credentials."""

    id: str
    client_id: str
    name: str = ""
    description: str = ""
    enabled: bool = False
    public: bool = False
    service_accounts_enabled: bool = False
    full_scope_allowed: bool = False


class AdminUserSummary(AdminModel):
    """Describe a group member using safe identity fields."""

    id: str
    username: str
    email: str = ""


class AdminClientRoles(AdminModel):
    """Group role mappings by client."""

    id: str
    client_id: str
    roles: list[AdminRole]


class AdminRoleMappings(AdminModel):
    """Separate realm and client role mappings."""

    realm_roles: list[AdminRole]
    clients: list[AdminClientRoles]


class AdminGroupPage(AdminModel):
    """Return one bounded page of groups."""

    items: list[AdminGroup]
    first: int
    max: int
    has_more: bool


class AdminRolePage(AdminModel):
    """Return one bounded page of realm roles."""

    items: list[AdminRole]
    first: int
    max: int
    has_more: bool


class AdminClientPage(AdminModel):
    """Return one bounded page of clients."""

    items: list[AdminClient]
    first: int
    max: int
    has_more: bool


class AdminUserAccess(AdminModel):
    """Describe a user's direct and effective access."""

    groups: list[AdminGroup]
    groups_truncated: bool
    direct: AdminRoleMappings
    effective_realm_roles: list[AdminRole]


class AdminGroupDetail(AdminModel):
    """Describe one group's hierarchy, members, and role mappings."""

    group: AdminGroup
    subgroups: list[AdminGroup]
    subgroups_truncated: bool
    members: list[AdminUserSummary]
    members_truncated: bool
    direct: AdminRoleMappings
    effective_realm_roles: list[AdminRole]


class AdminClientAccess(AdminModel):
    """Describe client roles, token scope, and service-account assignments."""

    client: AdminClient
    defined_roles: list[AdminRole]
    roles_truncated: bool
    token_scope_roles: AdminRoleMappings
    service_account_roles: AdminRoleMappings | None = None
