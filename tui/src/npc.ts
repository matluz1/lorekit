/**
 * NPC system — builds context and spawns persistent agent processes
 * for isolated NPC conversations. The process stays alive for the
 * duration of the /talk session and is killed on Escape/leave.
 */
import {
  getCharacter,
  getCharAttributes,
  getInventory,
  getAbilities,
  getSession,
  getTimeline,
} from "./db.js";
import type { Provider, ProviderOptions, AgentProcess } from "./provider.js";

/** MCP tools NPCs are allowed to use (read-only + dice + semantic search). */
const NPC_ALLOWED_TOOLS = [
  "mcp__lorekit__character_view",
  "mcp__lorekit__character_get_attr",
  "mcp__lorekit__character_get_items",
  "mcp__lorekit__character_get_abilities",
  "mcp__lorekit__roll_dice",
  "mcp__lorekit__timeline_list",
  "mcp__lorekit__timeline_search",
  "mcp__lorekit__journal_list",
  "mcp__lorekit__journal_search",
  "mcp__lorekit__recall_search",
  "mcp__lorekit__region_view",
  "mcp__lorekit__character_list",
];

/** Default model for NPCs — can be overridden per NPC via system/model attr. */
const DEFAULT_NPC_MODEL = "haiku";

export interface NpcContext {
  npcName: string;
  systemPrompt: string;
  model: string;
  /** Initial context message sent as the first user turn (timeline + situation). */
  initialContext: string;
}

/**
 * Build the system prompt, initial context, and determine the model for an NPC.
 * Reads personality, session setting, and NPC attributes from the DB.
 */
export function buildNpcContext(
  npcId: number,
  sessionId: number,
  pcName: string
): NpcContext | null {
  const npc = getCharacter(npcId);
  if (!npc) return null;

  const session = getSession(sessionId);
  if (!session) return null;

  const attrs = getCharAttributes(npcId);
  const inventory = getInventory(npcId);
  const abilities = getAbilities(npcId);

  // Extract personality from attributes
  const personalityAttr = attrs.find(
    (a) => a.category === "identity" && a.key === "personality"
  );
  const personality = personalityAttr?.value ?? "a common NPC";

  // Extract model override from attributes (system/model)
  const modelAttr = attrs.find(
    (a) => a.category === "system" && a.key === "model"
  );
  const model = modelAttr?.value ?? DEFAULT_NPC_MODEL;

  // Build identity section from non-system attributes
  const identityLines = attrs
    .filter((a) => a.category !== "system")
    .map((a) => `  ${a.key}: ${a.value}`);

  // Build inventory section
  const invLines = inventory.map(
    (item) =>
      `  ${item.name}${item.quantity > 1 ? ` x${item.quantity}` : ""}${item.equipped ? " (equipped)" : ""}`
  );

  // Build abilities section
  const abilityLines = abilities.map(
    (ab) => `  ${ab.name} (${ab.uses}): ${ab.description}`
  );

  const systemPrompt = `You are ${npc.name}, ${personality}.

World setting: ${session.setting}
Rule system: ${session.system_type}

Your attributes:
${identityLines.length > 0 ? identityLines.join("\n") : "  (none)"}

Your inventory:
${invLines.length > 0 ? invLines.join("\n") : "  (none)"}

Your abilities:
${abilityLines.length > 0 ? abilityLines.join("\n") : "  (none)"}

Rules:
- Respond only as this character, in first person
- You only know what this character would reasonably know
- Do not invent world facts beyond what is provided in your context
- Be concise
- Stay in character at all times
- Do not narrate the player's actions or put words in their mouth
- NEVER make attacks, deal damage, or resolve combat mechanics — combat is handled exclusively by the Game Master, not in dialogue
- This is a conversation. You may describe body language, emotions, and intentions, but do not roll dice or execute game actions

Tools — you have access to read-only tools to recall context:
- Use recall_search to remember past events relevant to the conversation
- Use timeline_list / timeline_search to check recent events
- Use journal_list / journal_search for important story notes
- Use character_view / character_list to look up characters you interact with
- Use region_view to know about your current surroundings
Before responding to the player, search for relevant context if the topic requires memory of past events.`;

  // Build initial context from recent timeline
  const timeline = getTimeline(sessionId, 10);
  let initialContext = "";
  if (timeline.length > 0) {
    const entries = [...timeline]
      .reverse()
      .map((e) => `- ${e.summary || e.content.slice(0, 150)}`);
    initialContext += `Recent events:\n${entries.join("\n")}\n\n`;
  }
  initialContext += `The player character is ${pcName}. They approach you to talk. Wait for their first message.`;

  return { npcName: npc.name, systemPrompt, model, initialContext };
}

/**
 * Spawn a persistent NPC agent process.
 * The process stays alive for multi-turn dialogue and is killed
 * when the player leaves the conversation.
 */
export function spawnNpc(
  provider: Provider,
  npcCtx: NpcContext,
  baseOpts: Pick<ProviderOptions, "mcpConfig" | "cwd" | "onError">
): AgentProcess {
  return provider.spawn({
    systemPrompt: npcCtx.systemPrompt,
    mcpConfig: baseOpts.mcpConfig,
    cwd: baseOpts.cwd,
    model: npcCtx.model,
    allowedTools: NPC_ALLOWED_TOOLS,
    persist: true,
    onError: baseOpts.onError,
  });
}
