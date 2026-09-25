# Studio design system

Status: design direction for the upcoming UI refactor. This document does not describe the current implementation.

## Goal

Make AI Stack Studio feel like part of the neurwerk family while remaining an efficient operations dashboard. Use **daisyUI 5 on Tailwind CSS 4** for common controls and a **light-first neurwerk theme**. Keep product-specific layouts, charts, code viewers, and policy diagnostics purpose-built rather than forcing them into marketing-page patterns.

## Sources of truth

- Brand reference: `../../www/base/` and `../../www/consult/src/` (sibling repository at `/Users/pvonhafe/neurwerk.com/www/`). Both use the same color tokens, Inter/JetBrains Mono, spacing scale, light surfaces, and indigo-to-lavender accents. In particular, consult `css/config/_colors.css`, `_fonts.css`, `_spacing.css`, `css/objects/_buttons.css`, `_features.css`, and `css/utilities/_gradient.css` in either site.
- Studio implementation: `apps/web/app/globals.css`, `apps/web/app/layout.tsx`, `apps/web/components/`, and `apps/web/app/`. Studio currently uses inline, shadcn-inspired controls, Geist fonts, and a forced `.dark` root; some screens also contain hard-coded dark colors.
- Use the **shared brand tokens**, not the marketing site's fixed navigation or oversized hero sections. Studio is a signed-in application with more data and denser workflows.

## Visual principles

1. **Light by default.** White and soft cool-gray/lavender surfaces, dark readable text, clear borders. No automatic dark-mode switch based on system preference in this first iteration.
2. **Brand in the accents.** Indigo for primary actions, selected navigation, links, and focus; lavender for secondary/chart accents. Gradients are reserved for occasional headings or high-emphasis moments, not every button or data cell.
3. **Quiet, structured density.** Consistent alignment, ample breathing room around sections, compact but comfortable controls and tables, subtle surface hierarchy; avoid heavy shadows and decorative marketing treatments on operational data.
4. **Meaning stays visible.** Status, errors, selected items, charts, and PII results must be understandable from text/shape as well as color. Monospace remains available for IDs, YAML, timestamps, log lines, and code.

## Tokens

These are the source values from the base and consult sites. Configure a single Studio theme from them; avoid scattered hex values in components.

| Role | Value | Studio use |
| --- | --- | --- |
| Primary | `#5563AB` | Primary actions, links, focus, active navigation |
| On primary | `#FFFFFF` | Text/icons on primary |
| Primary container | `#EAECF5` | Selected rows, gentle callouts, active nav background |
| On primary container | `#2A3C96` | Text/icons on tinted primary surfaces |
| Secondary | `#7F8AC0` | Secondary data accent, restrained gradients |
| Secondary container | `#DEDFF5` | Secondary tinted surface |
| Surface / lowest | `#FFFFFF` | Page and elevated card surface |
| Surface low | `#F4F4F8` | App shell and quiet card background |
| Surface | `#EBEBF0` | Alternate sections and muted controls |
| Surface high | `#E0E0E6` | Stronger hover/selection background |
| On surface | `#212121` | Main text |
| On surface variant | `#5F5F6B` | Secondary text |
| Outline variant | `#C7C5D4` | Borders and dividers |
| Error container / text | `#FFE5E5` / `#8B0000` | Error messages; do not use the brand's `#FF5E5E` with white text without checking contrast |
| Code background / text | `#13142A` / `#8B8FA8` | Deliberately dark code/log panels within the light shell, with contrast-adjusted syntax colors |

Typography: **Inter** for UI, **JetBrains Mono** for technical content, matching the sites' self-hosted font families. Use an app-friendly subset of the brand scale: page title ~28–32px, section title ~20–24px, body 14–16px, labels 12–14px. Preserve tabular numbers for metrics. Source fonts are under `../../www/base/assets/fonts/` and `../../www/consult/src/assets/fonts/`; bring necessary assets into Studio or use an equivalent locally hosted setup as part of implementation, without runtime dependence on the sibling checkout.

Spacing follows the site's 4/8/12/16/24/32/48px progression. Default control height ~40px; cards typically use 16–24px padding and 8–12px radius. Dashboard page gutters start at 16px on small screens and expand to 24–32px. Keep focus outlines clearly visible on light surfaces.

## daisyUI integration contract

- Add daisyUI 5 as a Tailwind v4 plugin in `apps/web/app/globals.css` via `@plugin "daisyui"`; define one named custom **light** theme using `@plugin "daisyui/theme"` with `default: true`, `prefersdark: false`, and `color-scheme: light`. Set the daisyUI base, content, primary, secondary, neutral, and semantic status colors plus radius/size variables from the tokens above.
- At the root, use the named theme (`data-theme`) and remove the forced `className="dark"`. Avoid a second conflicting source of truth for `--color-primary`, `--color-secondary`, etc.: daisyUI owns its theme variables; any retained Studio `bg-background`, `text-foreground`, `border-border`, `bg-sidebar`, or chart tokens must map explicitly to the same theme or be migrated away. Tailwind utility classes remain useful for layout, responsive behavior, and one-off spacing.
- Prefer daisyUI `btn`, `input`, `select`, `textarea`, `checkbox`, `badge`, `alert`, `card`, `tabs`, `table`, `loading`, and `skeleton` patterns where appropriate. Choose semantic variants (`primary`, `neutral`, `error`, etc.) consistently. App-specific widgets and data visualizations remain React components; daisyUI is a styling layer, not a replacement for application logic.
- Scope custom CSS to genuine brand or app needs (navigation, visualization, code, rich policy details). Do not import the marketing site's global CSS: its global `nav`/section selectors and layout rules are unsuitable for Studio.

## Component guidance

- **App shell and sidebar:** light low-surface background, fine right border, black neurwerk wordmark with a separate “Studio” label; active item uses primary-container/on-primary-container, keyboard focus is visible. Keep collapse and role-based navigation behavior. On narrow screens ensure navigation and main content remain reachable without squeezing tables beyond usability.
- **Headers and cards:** clear page title, short supporting text when useful, then grouped sections on white/low surfaces with restrained borders. Use shadow only to signal elevation (e.g. popovers), not on every panel.
- **Forms and actions:** primary for the main action in a region, outlined/neutral for secondary actions, explicit destructive variant for irreversible actions. Every field has a visible label, helpful validation text, and a discernible disabled/loading state.
- **Tables and filters:** readable row dividers, aligned numbers, visible sorting/selection/pagination, filters that wrap on smaller screens, horizontal scrolling for genuinely wide data. Use status badges with labels; never encode enabled/verified/activity solely through hue.
- **Charts:** use a deliberate light-background palette anchored on indigo/lavender, with additional distinguishable series colors. Theme axes, grid, legend, tooltip, and empty states; replace current dark-specific usage-page styles and hard-coded colors. Preserve readable labels and text equivalents for metrics.
- **Logs, YAML, and diagnostics:** an intentionally dark inset code surface is acceptable inside the light UI. Preserve monospace, wrapping/scrolling, copyability, severity labels, and error emphasis. Policy simulation and findings need clear grouping and comparison rather than decorative gradients.
- **Loading, empty, and error states:** concise explanation and next action. Use the same semantic variants on all pages; preserve existing authorization and data-loading behavior.

## Refactor order

1. Add the daisyUI dependency and light custom theme; establish fonts, brand tokens, and a small shared set of component conventions. Update root layout and app shell first.
2. Update shared navigation, forms, buttons, cards, tables, status indicators, loading/error states. Remove obsolete dark-specific overrides and conflicting token definitions as consumers migrate.
3. Work through all routes: profile and API keys; users, groups, roles, clients; usage and charts; logs; PII policy editor/tester and YAML preview; authentication/loading screens. Cover role-dependent variants.
4. Check keyboard navigation, focus, contrast, text overflow, empty/error/loading states, and small-screen behavior. Run web lint, typecheck, tests, and build; inspect representative pages visually in a browser before considering the refactor complete.

## Acceptance criteria

- Default Studio appearance is recognizably neurwerk and light, with the same brand palette and typographic character as base/consult; browser-native controls also use a light color scheme.
- Common controls use daisyUI consistently without overwriting important Studio behaviors or introducing token clashes with Tailwind.
- Every route, including charts, logs, diagnostics, and role-gated pages, is legible and usable in the light shell at desktop and narrow viewport widths.
- Contrast, focus indication, form labels, status text, and chart legends remain usable; no page depends on dark-only styles for readability.
- No runtime asset references point into the sibling `www` repository.

Implementation reference: [daisyUI v5 custom themes](https://daisyui.com/docs/themes/) (Tailwind v4 CSS `@plugin` configuration).
