# ADR-003: Agent Memory

## Status

Proposed

## Date

2026-02-18

## Context

After each run, the agent clears its memory. We want the ability to manage state across multiple layers: per session and per user.

**Problems to solve:**

1. Cache for reusable data
2. Shared memory between agents
3. If a user returns to the agent, we want the session to resume
4. Certain data should be shared across sessions

- **Short-term Memory (STM):** Enables agents to maintain recent context within an active session (conversation history), supporting coherent interaction and task coordination across agents.
- **Long-term Memory (LTM):** Provides persistence of information across sessions, allowing agents to recall knowledge, preferences, and outcomes over time for personalized experiences.

```txt
┌──────────────────────────────────────────────────────────────┐
│                         Agent Runtime                        │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │                     Memory Scope                     │   │
│   │                                                      │   │
│   │   ┌──────────────────────────────┐                   │   │
│   │   │ Short-Term Memory            │                   │   │
│   │   │ (Per-Session State)          │                   │   │
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

## Short-Term Memory

### Session Store

Uses [`AgentSession`](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/session?pivots=programming-language-python) to persist and resume per-user sessions via Redis.

- Serialize session state: `serialized_session = session.to_dict()`
- Deserialize on resume: `resumed_session = AgentSession.from_dict(serialized_session)`
- Store per user in a Redis key-value store

---

### Shared Context

[Context providers](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/context-providers?pivots=programming-language-python) are an extensibility mechanism in the Microsoft Agent Framework that automatically inject relevant information into an agent's conversation before the AI model processes each message (`before_run`) and optionally after (`after_run`).

#### FoundryMemoryProvider

The [Foundry Memory context provider](https://github.com/microsoft/agent-framework/blob/main/python/packages/azure-ai/README.md) enables semantic memory capabilities for agents using Azure AI Foundry Memory Store. It automatically:

- Retrieves static (user profile) memories on first run
- Searches for contextual memories based on conversation
- Updates the memory store with new conversation messages

See more in the [examples](https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/context_providers/azure_ai_foundry_memory.py)

#### RedisContextProvider

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

---

## Long-Term Memory

### Foundry Memory

[Foundry Memory](<(https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-memory?tabs=conversational-agent)>) is a managed, long-term memory solution built into Azure AI Foundry. 
There are two different integration patterns, and they behave differently:

- Memory Store via Agent Tool (MemorySearchTool): Writes new memories, used when the agent should store information from a conversation

- Memory Store via Context Provider (FoundryMemoryProvider): Reads stored memories, injects relevant context into the agent before each run

Memories written via tool call are available to the context provider, but context injected by the provider is not automatically persisted back to the memory store.

#### Use memories via agent tool

```txt
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

### Mem0ContextProvider

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

## Provider Comparison

| Provider                       | Use Case                                 | Persistence             | Search             |
| ------------------------------ | ---------------------------------------- | ----------------------- | ------------------ |
| `InMemoryHistoryProvider`      | Prototyping, stateless apps              | Session only            | None               |
| `Custom BaseHistoryProvider`   | File/DB-backed storage                   | Your choice             | Your choice        |
| `RedisHistoryProvider`         | Fast persistent chat history             | Yes (Redis)             | None               |
| `RedisContextProvider`         | Searchable memory / RAG                  | Yes (Redis)             | Full-text + Hybrid |
| `Mem0ContextProvider`          | Long-term user memory                    | Yes (cloud/self-hosted) | Semantic           |
| `AzureAISearchContextProvider` | Enterprise RAG                           | Yes (Azure)             | Hybrid + Semantic  |
| `FoundryMemoryProvider`        | Longterm memory across sessions & agents | Yes (Azure)Semantic     | Yes                |

## Decisions

Use Foundry Memory via Agent Tool (MemorySearchTool) for long-term memory.
Rather than pre-injecting memory into every agent context, the agent retrieves memory on demand using the tool. This avoids context rot from over-injection while still enabling persistent, semantically searchable memory across sessions.

For short-term / session state, use AgentSession backed by Redis to serialize and resume per-user sessions.

## Consequences

### Data retention

#### How much context is enough?

To restrict what to save and what to exclude add explicit rules to instructions of `user_profile_details` in the Memory options:

```python
options = MemoryStoreDefaultOptions(
    chat_summary_enabled=True,
    user_profile_enabled=True,
    user_profile_details=(
        # What to capture
        "Extract and store: user preferences, stated goals, recurring context "
        "(e.g. domain, role, working style), and corrections the user makes to prior answers. "

        # What to skip
        "Do not store: one-off questions, small talk, or anything already captured in the profile. "
        "Exclude sensitive data: credentials, financials, precise location, age, health information. "

        # Relevance filter
        "Only store information that would be useful context in a future session with this user."
    ),
)
```

The MemorySearchTool does semantic search, so retrieval relevance is determined by how well the query matches stored memories. The agent constructs the query implicitly from the conversation context. Guide this with instructions:

```python
agent = client.as_agent(
    instructions="""You are a helpful assistant that answers general questions.

    Retrieval rules:
    - SEARCH memory when: the user asks something that could depend on their past context, preferences, or history
    - DO NOT SEARCH memory when: generic factual questions, greetings, or topics with no personal dimension
    - If retrieved memories conflict, use the most recent one and discard the older fact
    - Use retrieved memories only if they are directly relevant to the current question — ignore the rest
    """,
    tools=[tool],
)
```

#### How do we delete memory?
Deletion should be triggered by: a user request (right to erasure), a contradiction being resolved, or a memory exceeding its retention horizon.

- Delete by scope — removes all memories for a specific user while preserving the memory store structure:
    
    ```python
    pythonproject_client.beta.memory_stores.delete_scope(
        name=memory_store_name,
        scope="user_123"
    )
    ```

- Delete the memory store — removes the entire store and all memories across all scopes. Irreversible:
    
    ```python
    project_client.beta.memory_stores.delete(memory_store_name)
    ```

For compliance, build an explicit deletion workflow with an audit log — this does not come out of the box.
