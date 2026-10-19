// Loaded by `acm run` via `pi -e`. Registers the gateway providers described in the
// ACM_PI_PROVIDERS environment variable (JSON, contains no secrets: apiKey is a "$NAME"
// reference that Pi resolves itself). Nothing here is written to Pi's configuration.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  const raw = process.env.ACM_PI_PROVIDERS;
  if (!raw) return;
  for (const p of JSON.parse(raw)) {
    pi.registerProvider(p.alias, {
      name: p.name,
      baseUrl: p.baseUrl,
      apiKey: p.apiKey,
      api: p.api,
      ...(p.headers ? { headers: p.headers } : {}),
      // the extension API has no defaults; these are the ones models.json applies
      models: p.models.map((m: Record<string, unknown>) => ({
        type: "chat",
        reasoning: false,
        input: ["text"],
        contextWindow: 128000,
        maxTokens: 16384,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        ...m,
      })),
    });
  }
}
