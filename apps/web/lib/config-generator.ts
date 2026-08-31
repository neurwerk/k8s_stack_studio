/** PII Engine policy types, defaults, and generated client configuration. */

export interface SafetyRule {
  name: string;
  pattern: string;
  action: string;
  message: string;
}

export interface RouteTarget {
  name: string;
  model: string;
  provider: string;
  baseURL: string;
  when: string;
  authSecret?: string;
}

export interface ClassifierClass {
  name: string;
  patterns: string[];
}

export interface EntityPolicyEntry {
  entityType: string;
  action: string;
  routeClass?: string;
  params: Record<string, string>;
  patterns: string[];
}

export interface ConfigState {
  llmPolicyEngine: {
    enabled: boolean;
    extProcTimeout: string;
    extProcPort: number;
  };
  piiEngine: {
    pii: {
      analyzerLanguages: string[];
      scoreThreshold: number;
      timeout: number;
      defaultAction: string;
      defaultOperator: {
        type: string;
        masking_char: string;
        chars_to_mask: number;
        from_end: boolean;
      };
      analyzerEntities: string[];
      maskOnReroute: boolean;
      hashWindowHours: number;
      entityPolicies: EntityPolicyEntry[];
    };
    attachments: { policy: string };
    safety: { enabled: string[]; custom: SafetyRule[] };
    classifier: { defaultClass: string; classes: ClassifierClass[] };
    session: { enabled: boolean; ttlHours: number };
    notice: { rerouted: string; masked: string; showWhenNoPiiDetected: boolean };
    routing: { defaultTarget: string; targets: Record<string, string>[] };
    debug: boolean;
    logFormat: string;
  };
}

export const SAFETY_RULES = [
  { id: "prompt_injection", label: "Prompt Injection", key: "promptInjection" },
  { id: "jailbreak", label: "Jailbreak", key: "jailbreak" },
  {
    id: "system_prompt_extraction",
    label: "System Prompt Extraction",
    key: "systemPromptExtraction",
  },
  { id: "harmful_content", label: "Harmful Content", key: "harmfulContent" },
  { id: "encoding_evasion", label: "Encoding Evasion", key: "encodingEvasion" },
  { id: "self_harm", label: "Self Harm", key: "selfHarm" },
];

export const PRESET_ENTITIES = [
  "SENSITIVE_TEXT",
  "PERSON_NAME",
  "PHONE_NUMBER",
  "EMAIL_ADDRESS",
  "STREET_ADDRESS",
  "POSTAL_CODE",
  "CITY",
  "DATE_OF_BIRTH",
  "PLACE_OF_BIRTH",
  "IP_ADDRESS",
  "BANK_ACCOUNT",
  "IBAN",
  "CREDIT_CARD_NUMBER",
  "PASSPORT_NUMBER",
  "DRIVERS_LICENSE_NUMBER",
  "NATIONAL_ID_NUMBER",
  "BSN",
  "TAX_ID",
  "STEUERNUMMER",
  "VAT_NUMBER",
  "HEALTH_INSURANCE_ID",
  "MEDICAL_RECORD_ID",
  "USERNAME",
  "PASSWORD_OR_SECRET",
  "VEHICLE_REGISTRATION",
];

export const VALID_ACTIONS = [
  "pass",
  "block",
  "mask",
  "replace",
  "redact",
  "hash",
  "encrypt",
  "reversible_replace",
  "reroute",
];

export const CREDENTIAL_PATTERNS = [
  "\\bAKIA[0-9A-Z]{16}\\b",
  "\\bsk-[a-zA-Z0-9_-]{20,}\\b",
  "\\beyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\b",
  "-----BEGIN\\s+(RSA\\s+|EC\\s+|DSA\\s+|OPENSSH\\s+)?PRIVATE KEY-----",
];

export function createDefaultState(): ConfigState {
  return {
    llmPolicyEngine: { enabled: true, extProcTimeout: "60s", extProcPort: 9000 },
    piiEngine: {
      pii: {
        analyzerLanguages: ["en"],
        scoreThreshold: 0.45,
        timeout: 60,
        defaultAction: "block",
        defaultOperator: { type: "mask", masking_char: "*", chars_to_mask: 100, from_end: true },
        analyzerEntities: [],
        maskOnReroute: true,
        hashWindowHours: 24,
        entityPolicies: [
          { entityType: "PERSON_NAME", action: "replace", params: {}, patterns: [] },
          { entityType: "EMAIL_ADDRESS", action: "replace", params: {}, patterns: [] },
          {
            entityType: "CREDENTIAL",
            action: "replace",
            params: {},
            patterns: CREDENTIAL_PATTERNS,
          },
        ],
      },
      attachments: { policy: "block" },
      safety: { enabled: SAFETY_RULES.map((rule) => rule.key), custom: [] },
      classifier: { defaultClass: "general", classes: [] },
      session: { enabled: true, ttlHours: 24 },
      notice: {
        rerouted:
          "Note: This conversation is handled by a local model because it contains sensitive data.",
        masked: "Note: Sensitive data in this conversation was anonymized.",
        showWhenNoPiiDetected: true,
      },
      routing: { defaultTarget: "local/llama3.2:3b", targets: [] },
      debug: false,
      logFormat: "text",
    },
  };
}

function indent(level: number): string {
  return "  ".repeat(level);
}

function yamlString(value: string): string {
  return JSON.stringify(value);
}

function normalizedEntityPolicy(entry: EntityPolicyEntry): Record<string, unknown> {
  const policy: Record<string, unknown> = {
    entityType: entry.entityType,
    action: entry.action,
    patterns: entry.patterns,
  };
  if (entry.routeClass) policy.routeClass = entry.routeClass;
  for (const [key, value] of Object.entries(entry.params)) {
    if (key === "chars_to_mask") policy[key] = Number(value);
    else if (key === "from_end") policy[key] = value === "true";
    else if (key !== "key") policy[key] = value;
  }
  return policy;
}

/** Convert editable UI state into the engine-owned request-local policy schema. */
export function toPolicyOverride(policy: ConfigState["piiEngine"]): Record<string, unknown> {
  return {
    ...policy,
    pii: {
      ...policy.pii,
      entityPolicies: policy.pii.entityPolicies.map(normalizedEntityPolicy),
    },
  };
}

function appendEntityPolicies(policy: ConfigState["piiEngine"]["pii"], lines: string[]): void {
  lines.push(`${indent(3)}entityPolicies:`);
  if (policy.entityPolicies.length === 0) {
    lines.push(`${indent(4)}[]`);
    return;
  }
  for (const entry of policy.entityPolicies) {
    lines.push(`${indent(4)}- entityType: ${yamlString(entry.entityType)}`);
    lines.push(`${indent(5)}action: ${yamlString(entry.action)}`);
    if (entry.routeClass) lines.push(`${indent(5)}routeClass: ${yamlString(entry.routeClass)}`);
    for (const [key, value] of Object.entries(normalizedEntityPolicy(entry))) {
      if (["entityType", "action", "routeClass", "patterns"].includes(key)) continue;
      lines.push(
        `${indent(5)}${key}: ${typeof value === "string" ? yamlString(value) : String(value)}`,
      );
    }
    if (entry.patterns.length > 0) {
      lines.push(
        `${indent(5)}patterns:`,
        ...entry.patterns.map((pattern) => `${indent(6)}- ${yamlString(pattern)}`),
      );
    }
  }
}

function appendPolicy(policy: ConfigState["piiEngine"], lines: string[]): void {
  const pii = policy.pii;
  lines.push(
    "# Shared policy core owned by pii-engine",
    "monitorPiiEngine:",
    `${indent(1)}policy:`,
    `${indent(2)}pii:`,
  );
  lines.push(`${indent(3)}analyzerLanguages: ${JSON.stringify(pii.analyzerLanguages)}`);
  lines.push(
    `${indent(3)}scoreThreshold: ${pii.scoreThreshold}`,
    `${indent(3)}timeout: ${pii.timeout}`,
  );
  lines.push(
    `${indent(3)}defaultAction: ${yamlString(pii.defaultAction)}`,
    `${indent(3)}defaultOperator:`,
  );
  lines.push(
    `${indent(4)}type: ${yamlString(pii.defaultOperator.type)}`,
    `${indent(4)}masking_char: ${yamlString(pii.defaultOperator.masking_char)}`,
  );
  lines.push(
    `${indent(4)}chars_to_mask: ${pii.defaultOperator.chars_to_mask}`,
    `${indent(4)}from_end: ${pii.defaultOperator.from_end}`,
  );
  lines.push(`${indent(3)}analyzerEntities: ${JSON.stringify(pii.analyzerEntities)}`);
  lines.push(
    `${indent(3)}maskOnReroute: ${pii.maskOnReroute}`,
    `${indent(3)}hashWindowHours: ${pii.hashWindowHours}`,
  );
  appendEntityPolicies(pii, lines);
  lines.push(
    `${indent(2)}attachments:`,
    `${indent(3)}policy: ${yamlString(policy.attachments.policy)}`,
  );
  lines.push(`${indent(2)}safety:`, `${indent(3)}enabled:`);
  if (policy.safety.enabled.length === 0) lines.push(`${indent(4)}[]`);
  else lines.push(...policy.safety.enabled.map((rule) => `${indent(4)}- ${yamlString(rule)}`));
  lines.push(`${indent(3)}custom:`);
  if (policy.safety.custom.length === 0) lines.push(`${indent(4)}[]`);
  else
    for (const rule of policy.safety.custom) {
      lines.push(
        `${indent(4)}- name: ${yamlString(rule.name)}`,
        `${indent(5)}pattern: ${yamlString(rule.pattern)}`,
        `${indent(5)}action: ${yamlString(rule.action)}`,
        `${indent(5)}message: ${yamlString(rule.message)}`,
      );
    }
  lines.push(
    `${indent(2)}classifier:`,
    `${indent(3)}defaultClass: ${yamlString(policy.classifier.defaultClass)}`,
    `${indent(3)}classes:`,
  );
  if (policy.classifier.classes.length === 0) lines.push(`${indent(4)}[]`);
  else
    for (const item of policy.classifier.classes)
      lines.push(
        `${indent(4)}- name: ${yamlString(item.name)}`,
        `${indent(5)}patterns: ${JSON.stringify(item.patterns)}`,
      );
  lines.push(
    `${indent(2)}session:`,
    `${indent(3)}enabled: ${policy.session.enabled}`,
    `${indent(3)}ttlHours: ${policy.session.ttlHours}`,
  );
  lines.push(
    `${indent(2)}notice:`,
    `${indent(3)}rerouted: ${yamlString(policy.notice.rerouted)}`,
    `${indent(3)}masked: ${yamlString(policy.notice.masked)}`,
    `${indent(3)}showWhenNoPiiDetected: ${policy.notice.showWhenNoPiiDetected}`,
  );
  lines.push(
    `${indent(2)}routing:`,
    `${indent(3)}defaultTarget: ${yamlString(policy.routing.defaultTarget)}`,
    `${indent(3)}targets: ${JSON.stringify(policy.routing.targets)}`,
  );
  lines.push(
    `${indent(2)}debug: ${policy.debug}`,
    `${indent(2)}logFormat: ${yamlString(policy.logFormat)}`,
  );
}

/** Generate values using the chart and PII Engine policy schema. */
export function generateYaml(state: ConfigState): string {
  const lines = [
    "# AgentGateway transport configuration",
    "guardrails:",
    `${indent(1)}llmPolicyEngine:`,
    `${indent(2)}enabled: ${state.llmPolicyEngine.enabled}`,
    `${indent(2)}extProcTimeout: ${yamlString(state.llmPolicyEngine.extProcTimeout)}`,
    `${indent(2)}extProcPort: ${state.llmPolicyEngine.extProcPort}`,
    "",
  ];
  appendPolicy(state.piiEngine, lines);
  return `${lines.join("\n")}\n`;
}
