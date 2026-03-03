
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

## Provider Comparison

| Provider | Use Case | Persistence | Search |
|---|---|---|---|
| `InMemoryHistoryProvider` | Prototyping, stateless apps | Session only | None |
| `Custom BaseHistoryProvider` | File/DB-backed storage | Your choice | Your choice |
| `RedisHistoryProvider` | Fast persistent chat history | Yes (Redis) | None |
| `RedisContextProvider` | Searchable memory / RAG | Yes (Redis) | Full-text + Hybrid |
| `Mem0ContextProvider` | Long-term user memory | Yes (cloud/self-hosted) | Semantic |
| `AzureAISearchContextProvider` | Enterprise RAG | Yes (Azure) | Hybrid + Semantic |
| `Neo4jContextProvider` | Graph-enriched knowledge | Yes (Neo4j) | Vector + Graph |

## Use Foundry Memory

### Use memories via agent tool

```

TODO: What are the differences between use Memory Store via agent tool vs use context provider?


```

### FoundryMemoryProvider

Memory in Foundry Agent Service is a managed, long-term memory solution. The Foundry Memory context provider enables semantic memory capabilities for agents using Azure AI Foundry Memory Store. It automatically:

- Retrieves static (user profile) memories on first run
- Searches for contextual memories based on conversation
- Updates the memory store with new conversation messages
