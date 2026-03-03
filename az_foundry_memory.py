"""Azure AI Memory Store agent served via Agent Framework DevUI.

Converts the memory-store test script into an interactive chat UI.
The agent uses a custom MemoryStoreContextProvider that:
  - Searches the memory store for relevant memories before each turn
  - Updates the memory store with new conversation content after each turn

Required environment variables:
  - AZURE_AI_PROJECT_ENDPOINT (or FOUNDRY_PROJECT_ENDPOINT)
  - AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME (or AZURE_OPENAI_CHAT_DEPLOYMENT_NAME)
  - AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME  (default: text-embedding-3-small)
"""

import asyncio
import logging
import os
from typing import Any

from agent_framework import AgentSession, BaseContextProvider, SessionContext
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    MemorySearchOptions,
    MemoryStoreDefaultDefinition,
    MemoryStoreDefaultOptions,
)
from azure.identity import AzureCliCredential, DefaultAzureCredential
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Memory-store context provider
# ---------------------------------------------------------------------------

class MemoryStoreContextProvider(BaseContextProvider):
    """Bridges the Azure AI Projects Memory Store into agent_framework sessions.

    * ``before_run`` – searches the store for memories relevant to the latest
      user messages and injects them into the system prompt.
    * ``after_run``  – sends the latest exchange to the store so new memories
      can be extracted asynchronously.
    """

    def __init__(
        self,
        project_client: AIProjectClient,
        memory_store_name: str,
        scope: str,
        max_memories: int = 10,
        update_delay: int = 5,
    ) -> None:
        super().__init__("memory-store")
        self._project_client = project_client
        self._memory_store_name = memory_store_name
        self._scope = scope
        self._max_memories = max_memories
        self._update_delay = update_delay

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _to_items(messages, last_n: int = 5) -> list[dict[str, str]]:
        """Convert the last *n* framework messages to memory-API items."""
        items: list[dict[str, str]] = []
        for msg in messages[-last_n:]:
            if hasattr(msg, "role") and hasattr(msg, "content"):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                items.append({"role": msg.role, "content": content, "type": "message"})
        return items

    # -- hooks ---------------------------------------------------------------

    async def before_run(
        self,
        *,
        agent: Any,
        session: AgentSession | None,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        items = self._to_items(context.get_messages(include_input=True))
        if not items:
            return

        try:
            previous_search_id = state.get(self.source_id, {}).get("last_search_id")
            search_response = await asyncio.to_thread(
                self._project_client.memory_stores.search_memories,
                name=self._memory_store_name,
                scope=self._scope,
                items=items,
                previous_search_id=previous_search_id,
                options=MemorySearchOptions(max_memories=self._max_memories),
            )

            if search_response.memories:
                memory_text = "\n".join(
                    f"- {m.memory_item.content}" for m in search_response.memories
                )
                context.extend_instructions(
                    self.source_id,
                    f"The following memories are stored about this user:\n{memory_text}\n"
                    "Use these memories to personalize your responses when relevant.",
                )
                logger.info("Injected %d memories into context", len(search_response.memories))

            state.setdefault(self.source_id, {})["last_search_id"] = search_response.search_id
        except Exception:
            logger.warning("Memory search failed", exc_info=True)

    async def after_run(
        self,
        *,
        agent: Any,
        session: AgentSession | None,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        items = self._to_items(
            context.get_messages(include_input=True, include_response=True),
            last_n=2,
        )
        if not items:
            return

        try:
            poller = await asyncio.to_thread(
                self._project_client.memory_stores.begin_update_memories,
                name=self._memory_store_name,
                scope=self._scope,
                items=items,
                update_delay=self._update_delay,
            )
            logger.info("Memory update scheduled (ID: %s)", poller.update_id)
        except Exception:
            logger.warning("Memory update failed", exc_info=True)


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def _ensure_memory_store(
    project_client: AIProjectClient,
    name: str,
    chat_model: str,
    embedding_model: str,
) -> None:
    """Create the memory store (delete first if it already exists)."""
    try:
        project_client.memory_stores.delete(name)
        logger.info("Deleted existing memory store '%s'", name)
    except Exception:
        pass

    options = MemoryStoreDefaultOptions(
        chat_summary_enabled=True,
        user_profile_enabled=True,
        user_profile_details=(
            "Avoid irrelevant or sensitive data, such as age, financials, "
            "precise location, and credentials"
        ),
    )
    definition = MemoryStoreDefaultDefinition(
        chat_model=chat_model,
        embedding_model=embedding_model,
        options=options,
    )
    store = project_client.memory_stores.create(
        name=name,
        definition=definition,
        description="Memory store for DevUI assistant",
    )
    logger.info("Created memory store: %s (%s)", store.name, store.id)


# ---------------------------------------------------------------------------
# Main – launch DevUI
# ---------------------------------------------------------------------------

def main() -> None:
    from agent_framework_devui import serve

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # --- resolve env vars ---------------------------------------------------
    project_endpoint = os.environ.get(
        "AZURE_AI_PROJECT_ENDPOINT",
        os.environ.get("FOUNDRY_PROJECT_ENDPOINT", ""),
    )
    chat_model = os.environ.get(
        "AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME",
        os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", ""),
    )
    embedding_model = os.environ.get(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"
    )

    memory_store_name = "my_memory_store"
    scope = "user_123"

    # --- project client (for memory store API) ------------------------------
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)

    # --- ensure memory store exists -----------------------------------------
    _ensure_memory_store(project_client, memory_store_name, chat_model, embedding_model)

    # --- build the agent ----------------------------------------------------
    responses_client = AzureOpenAIResponsesClient(
        project_endpoint=project_endpoint,
        deployment_name=chat_model,
        credential=AzureCliCredential(),
    )

    memory_provider = MemoryStoreContextProvider(
        project_client=project_client,
        memory_store_name=memory_store_name,
        scope=scope,
    )

    agent = responses_client.as_agent(
        name="MemoryAssistant",
        instructions=(
            "You are a helpful assistant that answers general questions. "
            "When the user tells you something personal (preferences, habits, etc.), "
            "acknowledge it warmly. Use any recalled memories to personalize your responses."
        ),
        context_providers=[memory_provider],
    )

    # --- serve --------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Starting Memory Store Agent (DevUI)")
    logger.info("=" * 60)
    logger.info("")
    logger.info("  Memory store : %s", memory_store_name)
    logger.info("  Scope        : %s", scope)
    logger.info("  Chat model   : %s", chat_model)
    logger.info("  Embedding    : %s", embedding_model)
    logger.info("")

    serve(entities=[agent], port=8090, auto_open=True)


if __name__ == "__main__":
    main()