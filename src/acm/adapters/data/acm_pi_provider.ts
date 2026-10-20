// Loaded by `acm run` via `pi -e`. Registers the gateway providers described in the
// ACM_PI_PROVIDERS environment variable (JSON, contains no secrets: apiKey is a "$NAME"
// reference that Pi resolves itself). Nothing here is written to Pi's configuration.
//
// When ACM_PI_ROUTER is set, it also registers the virtual model `acm/auto`: the thinking
// level selected on it picks the profile's role (low = fast, medium = default, high =
// reasoning). Follow-ups and retries stay on the model that answered, so prompt caches
// survive; background requests (compaction summaries) use the fast model only when its
// window is at least as large as the one they summarise.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Tier = { provider: string; model: string; thinking: string; context?: number | null };

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

  const router = process.env.ACM_PI_ROUTER;
  if (!router) return;
  const spec: { tiers: Record<string, Tier>; contextWindow?: number | null } = JSON.parse(router);
  const tier = (level: string | undefined): Tier => spec.tiers[level ?? ""] ?? spec.tiers.medium;
  pi.registerVirtualModel({
    provider: "acm",
    id: "auto",
    name: "Auto (low = fast, medium = default, high = reasoning)",
    thinkingLevels: ["low", "medium", "high"],
    ...(spec.contextWindow ? { contextWindow: spec.contextWindow } : {}),
    route(request, ctx) {
      const to = (t: Tier) => {
        const model = ctx.modelRegistry.find(t.provider, t.model);
        if (!model) throw new Error(`acm/auto: ${t.provider}/${t.model} is not registered`);
        return { model, thinkingLevel: t.thinking };
      };
      const sticky = request.failed ?? request.previous;
      const stay = sticky && { model: sticky.model, thinkingLevel: sticky.thinkingLevel ?? "medium" };
      if (request.reason === "direct") {
        const fast = tier("low");
        const current = sticky?.model.contextWindow ?? tier("medium").context;
        if (fast.context && current && fast.context >= current) return to(fast);
        return stay || to(tier("medium"));
      }
      if (request.reason !== "user" && stay) return stay;
      return to(tier(request.thinkingLevel));
    },
  });
}
