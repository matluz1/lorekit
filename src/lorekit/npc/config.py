"""NPC subsystem configuration constants.

Centralizes magic numbers used across prefetch, memory, postprocess,
reflect, and combat modules. All values are system-agnostic — they
control the NPC engine itself, not any particular game system.
"""

# --- Token budget ---
CHARS_PER_TOKEN = 4
DEFAULT_TOKEN_BUDGET = 6000
IDENTITY_RESERVE = 1500

# --- Budget allocation (fractions of remaining budget) ---
MEMORY_BUDGET_RATIO = 0.6
TIMELINE_BUDGET_RATIO = 0.25

# --- Memory retrieval ---
MIN_MEMORIES = 3
HOT_IMPORTANCE = 0.7
HOT_MEMORY_LIMIT = 20
FALLBACK_RECENT = 10

# --- Memory scoring ---
DEFAULT_IMPORTANCE = 0.5
RECENCY_DECAY = 0.995

# --- Reflection & pruning ---
REFLECTION_THRESHOLD = 5.0
PRUNE_IMPORTANCE = 0.3
PRUNE_RECENCY = 0.01

# --- Core identity ---
CORE_FIELD_CAP = 2000

# --- Subprocess timeouts (seconds) ---
INTERACT_TIMEOUT = 120
REFLECT_TIMEOUT = 120
REACTION_TIMEOUT = 30
