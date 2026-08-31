import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ["eslint.config.mjs", "postcss.config.mjs"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/explicit-function-return-type": "off",
      "@typescript-eslint/consistent-type-imports": ["error", { prefer: "type-imports" }],
      "@typescript-eslint/no-deprecated": "off",
    },
  },
  {
    ignores: [
      "**/.next/**",
      "**/node_modules/**",
      "**/public/**",
      "**/postcss.config.mjs",
    ],
  },
  {
    // Legacy files — suppress violations that will be fixed in follow-up PRs
    // TODO(2026-08): remove these ignores as each file is refactored
    files: [
      "app/layout.tsx",
      "app/logs/page.tsx",
      "app/users/**/page.tsx",
      "app/clients/page.tsx",
      "app/auth/callback/page.tsx",
      "components/api-key-manager.tsx",
      "components/api-key-list.tsx",
      "components/user-table.tsx",
      "components/oidc-provider.tsx",
      "components/auth-guard.tsx",
      "components/config-preview.tsx",
      "lib/api/client.ts",
      "lib/api/admin.ts",
      "lib/api/logs.ts",
      "lib/auth/roles.ts",
      "lib/oidc/settings.ts",
      "components/sidebar.tsx",
      "next.config.ts",
      // Legacy files — TODO(2026-08): C2+H2 will split and clean config-panel + config-generator
      "components/config-panel.tsx",
      "components/config-panel/entity-row.tsx",
      "components/config-panel/route-target-row.tsx",
      "components/config-panel/safety-rule-row.tsx",
      "components/config-panel/classifier-class-row.tsx",
      "components/config-panel/operator-params.tsx",
      "components/config-panel/pattern-editor.tsx",
      "components/config-panel/param-input.tsx",
      "components/config-panel/primary-span.tsx",
      "lib/config-generator.ts",
    ],
    rules: {
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-return": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/restrict-template-expressions": "off",
      "@typescript-eslint/no-misused-promises": "off",
      "@typescript-eslint/no-confusing-void-expression": "off",
      "@typescript-eslint/no-floating-promises": "off",
      "@typescript-eslint/prefer-nullish-coalescing": "off",
      "@typescript-eslint/use-unknown-in-catch-callback-variable": "off",
      "@typescript-eslint/require-await": "off",
      "@typescript-eslint/no-unnecessary-type-parameters": "off",
      "@typescript-eslint/no-unnecessary-condition": "off",
      "react-hooks/exhaustive-deps": "warn",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/rules-of-hooks": "warn",
      "@typescript-eslint/unbound-method": "off",
      "no-unused-expressions": "off",
    },
  },
);
