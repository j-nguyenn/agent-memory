# Agent Memory

## Context

After each run, the agent clears its memory. We want the ability to manage state across multiple layers: per session and per user.

**Problems to solve:**

1. Cache for reusable data
2. Shared memory between agents
3. If a user returns to the agent, we want the session to resume
4. Certain data should be shared across sessions

```
┌──────────────────────────────────────────────────────────────┐
│                         Agent Runtime                        │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │                     Memory Scope                     │   │
│   │                                                      │   │
│   │   ┌──────────────────────────────┐                   │   │
│   │   │ Session Store                │                   │   │
│   │   │ (Per-Session State)          │                   │   │
│   │   └──────────────────────────────┘                   │   │
│   │                                                      │   │
│   │   ┌──────────────────────────────┐                   │   │
│   │   │ Shared Context               │                   │   │
│   │   │ (Cross-Agent State)          │                   │   │
│   │   └──────────────────────────────┘                   │   │
│   │                                                      │   │
│   │   ┌──────────────────────────────┐                   │   │
│   │   │ Global Cache                 │                   │   │
│   │   │ (Ephemeral / Reusable Data)  │                   │   │
│   │   └──────────────────────────────┘                   │   │
│   │                                                      │   │
│   │   ┌──────────────────────────────┐                   │   │
│   │   │ Long-Term Memory             │                   │   │
│   │   │ (Cross-Session Persistent)   │                   │   │
│   │   └──────────────────────────────┘                   │   │
│   │                                                      │   │
│   └──────────────────────────────────────────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Use Agent Context Providers

Context providers are an extensibility mechanism in the Microsoft Agent Framework that automatically inject relevant information into an agent's conversation before the AI model processes each message (`before_run`) and optionally after (`after_run`).

- **Short-term Memory (STM):** Enables agents to maintain recent context within an active session (conversation history), supporting coherent interaction and task coordination across agents.
- **Long-term Memory (LTM):** Provides persistence of information across sessions, allowing agents to recall knowledge, preferences, and outcomes over time for personalized experiences.

---

## Memory Layers

### 1. Session Store

Uses [`AgentSession`](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/session?pivots=programming-language-python) to persist and resume per-user sessions via Redis.

- Serialize session state: `serialized_session = session.to_dict()`
- Deserialize on resume: `resumed_session = AgentSession.from_dict(serialized_session)`
- Store per user in a Redis key-value store

**Addresses problem:** (3) Resume session when user returns

---

### 2. Shared Context

Uses [`RedisContextProvider`](https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/context_providers/redis/README.md) to inject instructions, RAG content, or metadata shared between agents.

**Features:**

- Full-text and hybrid vector search (set `vectorizer_choice` to `"openai"` or `"hf"` to enable embeddings)
- When using a vectorizer, also set `vector_field_name` (e.g., `"vector"`)
- Partition fields for scoping: `application_id`, `agent_id`, `user_id`, `thread_id`
- Thread scoping: `scope_to_per_operation_thread_id=True` isolates memory per operation thread
- Index management: `index_name`, `overwrite_redis_index`, `drop_redis_index`

```python
# Create Azure Redis Context provider
context_provider = RedisContextProvider(
    source_id="redis_memory",
    redis_url=redis_url,
    index_name="chat_context",
    prefix="chat_context",
    user_id="demo-user",
)

agent = client.as_agent(
    name="RedisMemoryAssistant",
    instructions="You are a helpful assistant. Use prior conversation context when relevant.",
    context_providers=[context_provider],
)
```

**Addresses problem:** (2) Shared memory between agents

---

### 3. Global Cache

Uses [`RedisHistoryProvider`](https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/context_providers/redis/azure_redis_conversation.py) and `RedisContextProvider` for fast, ephemeral, reusable data across agents.

```python
# Create Azure Redis history provider
history_provider = RedisHistoryProvider(
    source_id="redis_memory",
    credential_provider=credential_provider,
    host=redis_host,
    port=10000,
    ssl=True,
    key_prefix="chat_messages",
    max_messages=100,
)

# Create agent with Azure Redis history provider
agent = client.as_agent(
    name="AzureRedisAssistant",
    instructions="You are a helpful assistant.",
    context_providers=[history_provider],
)
```

**Addresses problem:** (1) Cache for reusable data

---

### 4. Long-Term Memory

#### Option B: Mem0ContextProvider

[`Mem0`](https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/context_providers/mem0/README.md) is a self-improving memory layer for LLMs that enables long-term memory capabilities across sessions, integrating with Mem0's API via a context provider.

```python
agent_id_1 = "agent_personal"
agent_id_2 = "agent_work"

async with (
    AzureCliCredential() as credential,
    AzureAIAgentClient(credential=credential).as_agent(
        name="PersonalAssistant",
        instructions="You are a personal assistant that helps with personal tasks.",
        context_providers=[
            Mem0ContextProvider(
                source_id="mem0",
                agent_id=agent_id_1,
            )
        ],
    ) as personal_agent,
    AzureAIAgentClient(credential=credential).as_agent(
        name="WorkAssistant",
        instructions="You are a work assistant that helps with professional tasks.",
        context_providers=[
            Mem0ContextProvider(
                source_id="mem0",
                agent_id=agent_id_2,
            )
        ],
    ) as work_agent,
):
    result = await personal_agent.run("Remember that I like to exercise at 6 AM and prefer outdoor activities.")
    result = await work_agent.run("Remember that I have team meetings every Tuesday at 2 PM.")

    # Memory is scoped per agent_id — agents cannot see each other's memories
    result = await personal_agent.run("What do you know about my schedule?")
    result = await work_agent.run("What do you know about my schedule?")
```

#### Option C: Neo4jContextProvider

Using [Neo4j](https://neo4j.com/labs/genai-ecosystem/ms-agent-framework/#_context_provider_integration) Graph-enriched retrieval combining vector search with graph traversal for rich, relational context.

```python
# Graph-enriched retrieval query
# Appended after vector search by VectorCypherRetriever.
# Available variables from vector search:
#   - node: The Chunk node matched by vector similarity
#   - score: Similarity score (0.0 to 1.0)
RETRIEVAL_QUERY = """
MATCH (node)-[:FROM_DOCUMENT]->(doc:Document)<-[:FILED]-(company:Company)
OPTIONAL MATCH (company)-[:FACES_RISK]->(risk:RiskFactor)
OPTIONAL MATCH (company)-[:MENTIONS]->(product:Product)
WITH node, score, company, doc,
     collect(DISTINCT risk.name)[0..5] AS risks,
     collect(DISTINCT product.name)[0..5] AS products
WHERE score IS NOT NULL
RETURN
    node.text AS text,
    score,
    company.name AS company,
    company.ticker AS ticker,
    risks,
    products
ORDER BY score DESC
"""

provider = Neo4jContextProvider(
    uri=neo4j_settings.uri,
    username=neo4j_settings.username,
    password=neo4j_settings.get_password(),
    index_name=neo4j_settings.vector_index_name,
    index_type="vector",
    retrieval_query=RETRIEVAL_QUERY,
    embedder=embedder,
    top_k=5,
    context_prompt=(
        "## Graph-Enriched Knowledge Context\n"
        "The following information combines semantic search results with "
        "graph traversal to provide company, product, and risk context:"
    ),
)
```

**Addresses problem:** (4) Data shared across sessions

---

## Use Foundry Memory

[Foundry Memory](<(https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-memory?tabs=conversational-agent)>) is a managed, long-term memory solution built into Azure AI Foundry. It provides two integration patterns with distinct responsibilities:

There are two different integration patterns, and they behave differently:

- Memory Store via Agent Tool (MemorySearchTool): Writes new memories, used when the agent should store information from a conversation

- Memory Store via Context Provider (FoundryMemoryProvider): Reads stored memories, injects relevant context into the agent before each run

Memories written via tool call are available to the context provider, but context injected by the provider is not automatically persisted back to the memory store.

### Use memories via agent tool

```
Example
via tool call
> I wake up at 6 AM and go to the gym before work.
> Got it! I’ll remember: You wake up at 6 AM and go to the gym before work. How else can I assist you with your routine?

via context provider
> Suggest a good schedule for tomorrow.

> Based on your routine—waking up at 6 AM and going to the gym before work—here’s a suggested schedule for a productive day:

**6:00 AM** – Wake up
**6:00–6:30 AM** – Morning routine (freshen up, hydrate)
**6:30–7:30 AM** – Gym session
**7:30–8:00 AM** – Shower and get ready
**8:00–8:15 AM** – Healthy breakfast
**8:15–8:45 AM** – Prepare for work/commute
**9:00 AM–12:00 PM** – Focused work period
**12:00–1:00 PM** – Lunch break
**1:00–5:00 PM** – Continue with work/tasks
**5:00 PM onwards** – Wind down:
- **5:00–5:30 PM:** Quick walk or stretching
- **5:30–6:30 PM:** Personal time (hobbies, errands, reading)
- **6:30–7:30 PM:** Dinner
- **7:30–9:00 PM:** Relaxation (TV, family, light activities)
- **9:00–10:00 PM:** Prepare for bed (plan for next day, light reading, unwind)
- **10:00 PM:** Bedtime (for adequate sleep before 6 AM wake-up)

You can adjust any part to better fit your personal and work commitments! If you want suggestions for meal ideas or focus blocks, let me know.
> I also like to eat dinner before 6pm
> Thanks for sharing! I’ll remember that you like to eat dinner before 6pm. If you need help planning meals, structuring your day, or fitting in other activities around your early dinner, just let me know!



come back to tool call
> what time should I have dinner?
> Based on your routine—waking up at 6 AM, going to the gym before work, and likely having an earlier start to your day—a good time for dinner would be between **6:00 PM and 7:30 PM**. This allows:

- Enough time after dinner for digestion before bedtime.
- A reasonable gap between your last meal and when you’ll likely wind down for sleep.
- Support for recovery if you work out in the evenings as well.

If you typically go to bed around 10 PM, aim to have dinner at least 2–3 hours before sleeping. This helps with better sleep and overall digestion. Would you like tips on dinner timing if your bedtime is different?


===> the tool call doesn't have memory of the context provider when the context provider can access tool call memory

```

### FoundryMemoryProvider

Memory in Foundry Agent Service is a managed, long-term memory solution. The Foundry Memory context provider enables semantic memory capabilities for agents using Azure AI Foundry Memory Store. It automatically:

- Retrieves static (user profile) memories on first run
- Searches for contextual memories based on conversation
- Updates the memory store with new conversation messages

See more in the [examples](https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/context_providers/azure_ai_foundry_memory.py)

## Provider Comparison

| Provider                       | Use Case                                 | Persistence             | Search             |
| ------------------------------ | ---------------------------------------- | ----------------------- | ------------------ |
| `InMemoryHistoryProvider`      | Prototyping, stateless apps              | Session only            | None               |
| `Custom BaseHistoryProvider`   | File/DB-backed storage                   | Your choice             | Your choice        |
| `RedisHistoryProvider`         | Fast persistent chat history             | Yes (Redis)             | None               |
| `RedisContextProvider`         | Searchable memory / RAG                  | Yes (Redis)             | Full-text + Hybrid |
| `Mem0ContextProvider`          | Long-term user memory                    | Yes (cloud/self-hosted) | Semantic           |
| `AzureAISearchContextProvider` | Enterprise RAG                           | Yes (Azure)             | Hybrid + Semantic  |
| `Neo4jContextProvider`         | Graph-enriched knowledge                 | Yes (Neo4j)             | Vector + Graph     |
| `FoundryMemoryProvider`        | Longterm memory across sessions & agents | Yes (Azure)Semantic     | Yes                |

## Consequences

### Data retention

#### How much context is enough?

It depends on the agent's task and the cost of irrelevant context. General guidelines:

- **Conversation history:** Keep the most recent N messages (e.g., 10–50). The `RedisHistoryProvider` supports `max_messages` to cap this. Longer histories increase token usage and latency without proportional benefit. See [context window management](https://platform.openai.com/docs/guides/conversation-state).
- **Semantic memory (Foundry Memory, Mem0, Redis vector):** Retrieve only the top-k most relevant memories per turn (typically 3–10). All providers support a `top_k` or equivalent parameter. Returning too many results dilutes signal with noise.
- **Redis TTL:** For ephemeral/cache data, set a TTL on Redis keys (`EXPIRE`) to auto-evict stale entries. See [Redis key expiration](https://redis.io/docs/latest/commands/expire/).
- **Token budget rule of thumb:** Reserve ≥50 % of the model's context window for the current turn (user message + tool results + generation). Fill the remainder with history and retrieved context, prioritizing recency and relevance.

#### How do we delete memory?

Each provider has its own deletion mechanism:

| Provider                      | Deletion method                                                                                                                                                                                                                                                                                                                  |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Foundry Memory**            | Use the SDK: `client.beta.memory_stores.delete_memory(store_name, memory_id, scope)` to remove individual memories, or `client.beta.memory_stores.delete(store_name)` to delete the entire store. See [Delete memories](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/memory-usage?tabs=python#delete-memories). |
| **Redis (History & Context)** | Delete keys directly: `DEL <key>` or flush by prefix with `SCAN` + `DEL`. Set TTLs for automatic expiration. See [Redis DEL](https://redis.io/docs/latest/commands/del/).                                                                                                                                                        |
| **Mem0**                      | Use the Mem0 API: `client.delete(memory_id)` or `client.delete_all(user_id=...)`. See [Mem0 delete memories](https://docs.mem0.ai/features/delete-memories).                                                                                                                                                                     |
| **Neo4j**                     | Run Cypher queries: `MATCH (n:Memory {userId: $uid}) DETACH DELETE n`. See [Neo4j DELETE](https://neo4j.com/docs/cypher-manual/current/clauses/delete/).                                                                                                                                                                         |

**Compliance note:** For GDPR/right-to-erasure requests, ensure all stores that hold user data are covered — conversation history, semantic memory, and any vector index embeddings. Embeddings alone can leak information even if the source text is deleted; drop and re-index if needed.

#### What if there is contradictory data in memory?

Yes, contradictions introduce noise and can degrade response quality. Mitigation strategies:

- **Foundry Memory** handles this automatically: when you call `begin_update_memories`, the service uses an LLM to extract, deduplicate, and merge facts. If a new message contradicts an existing memory, the service updates or replaces it. See [How memory works](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-memory).
- **Mem0** similarly performs automatic conflict resolution during `add()` — it detects contradictions and updates existing memories rather than duplicating them. See [Mem0 memory operations](https://docs.mem0.ai/features/memory-operations).
- **Redis / Neo4j (manual stores):** These stores do **not** resolve contradictions automatically. You must implement your own deduplication logic:
  - Use timestamps to prefer the most recent fact.
  - Use metadata (e.g., `updated_at`, `source`) to rank conflicting entries.
  - Periodically run a cleanup job to detect and merge duplicates.
- **Prompt-level mitigation:** Instruct the agent (via system prompt) to prefer the most recent context when it detects conflicting information, e.g., _"If you find contradictory information in context, prefer the most recently provided fact and note the discrepancy."_

### Privacy & compliance

- **Data residency:** Foundry Memory stores data in the same region as your Azure AI project. Redis and Neo4j depend on your deployment configuration.
- **Encryption:** Azure-managed stores (Foundry, Azure Redis Cache) encrypt data at rest by default. For self-hosted Redis or Neo4j, enable TLS and disk encryption. See [Azure Redis security](https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-overview#security).
- **Access control:** Scope memories using `user_id`, `agent_id`, and `thread_id` partition fields to prevent cross-user or cross-agent data leakage. Foundry Memory scopes memories per `scope` parameter (typically set to user ID).
