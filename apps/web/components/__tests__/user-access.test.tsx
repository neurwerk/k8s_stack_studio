import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UserAccess } from "../user-access";

describe("UserAccess", () => {
  it("shows readable group memberships", () => {
    render(<UserAccess groups={[
      { id: "group-a", name: "Engineering", path: "/Engineering", subgroup_count: 0 },
      { id: "group-b", name: "Platform", path: "/Engineering/Platform", subgroup_count: 0 },
    ]} groupsTruncated={false} error={false} canViewGroup />);

    const groups = screen.getByRole("region", { name: "Group memberships" });
    expect(within(groups).getByRole("link", { name: "Engineering" })).toHaveAttribute(
      "href", "/groups/group-a",
    );
    expect(within(groups).getByRole("link", { name: "Platform" })).toHaveAttribute(
      "href", "/groups/group-b",
    );
  });

  it("shows a clear empty state when there are no memberships", () => {
    render(<UserAccess groups={[]} groupsTruncated={false} error={false} canViewGroup={false} />);
    expect(screen.getByText("No group memberships.")).toBeInTheDocument();
  });
});
