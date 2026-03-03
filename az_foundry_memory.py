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

import logging
import os

from agent_framework import Agent, InMemoryHistoryProvider
from agent_framework.azure import AzureOpenAIResponsesClient, FoundryMemoryProvider
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    MemorySearchTool,
    MemoryStoreDefaultDefinition,
    MemoryStoreDefaultOptions,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# azure-ai-projects==2.0.0b4
# agent-framework-core==1.0.0rc2

"""Follows the tutorial at:
https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/memory-usage?tabs=python

Steps:
    1. Create a memory store
    2. Attach MemorySearchPreviewTool to an Agent Framework agent
    3. Use DevUI for interactive chat and memory updates
"""

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

# -----------------------------------------------------------------------
# 1. Create a memory store
# -----------------------------------------------------------------------
credential = DefaultAzureCredential()

project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)

memory_store_name = "my_memory_store"

# Specify memory store options
options = MemoryStoreDefaultOptions(
    chat_summary_enabled=True,
    user_profile_enabled=True,
    user_profile_details=(
        "Avoid irrelevant or sensitive data, such as age, financials, "
        "precise location, and credentials"
    ),
)

# Create memory store
definition = MemoryStoreDefaultDefinition(
    chat_model=chat_model,
    embedding_model=embedding_model,
    options=options,
)

# Delete if it already exists so we start fresh
try:
    project_client.memory_stores.delete(memory_store_name)
    logger.info("Deleted existing memory store '%s'", memory_store_name)
except Exception:
    pass

memory_store = project_client.memory_stores.create(
    name=memory_store_name,
    definition=definition,
    description="Memory store for customer support agent",
)
print(f"Created memory store: {memory_store.name}")

# -----------------------------------------------------------------------
# 2. Use memories via an agent tool
# -----------------------------------------------------------------------

# Set scope to associate the memories with
# You can also use "{{$userId}}" to take the TID and OID of the request
# authentication header
scope = "user_123"

openai_client = project_client.get_openai_client()

# Create memory search tool
tool = MemorySearchTool(
    memory_store_name=memory_store_name,
    scope=scope,
    update_delay=1,  # Wait 1 second of inactivity before updating memories
    # In a real application, set this to a higher value like 300 (5 minutes, default)
)

# Create an Agent Framework agent for DevUI.
# DevUI requires entities that implement run(), which this agent does.
client = AzureOpenAIResponsesClient(
    project_endpoint=project_endpoint,
    deployment_name=chat_model,
    credential=credential,
)

agent = client.as_agent(
    name="MemoryAgentUsingTool",
    description="Helpful assistant with Azure AI Foundry Memory Store via tool calling",
    instructions="You are a helpful assistant that answers general questions.",
    tools=[tool],
)

print(f"Agent ready for DevUI (id: {agent.id}, name: {agent.name})")

memory_provider = FoundryMemoryProvider(
    project_client=project_client,
    memory_store_name=memory_store.name,
    scope=scope,  # Scope memories to a specific user, if not set, the session_id
    # will be used as scope, which means memories are only shared within the same session
    update_delay=0,  # Do not wait to update memories after each interaction (for demo purposes)
    # In production, consider setting a delay to batch updates and reduce costs
)
agent2 = Agent(
    name="MemoryAgentUsingContextProvider",
    client=client,
    description="Helpful assistant with Azure AI Foundry Memory Store via context provider",
    instructions="""You are a helpful assistant that remembers past conversations.
        The memories from previous interactions are automatically provided to you.""",
    context_providers=[memory_provider, InMemoryHistoryProvider(load_messages=False)],
    default_options={"store": False},
)
# # -----------------------------------------------------------------------
# # 3. Create a conversation
# # -----------------------------------------------------------------------

# # Create a conversation with the agent with memory tool enabled
# conversation = openai_client.conversations.create()
# print(f"Created conversation (id: {conversation.id})")

# # Create an agent response to initial user message
# response = openai_client.responses.create(
#     input="I prefer dark roast coffee",
#     conversation=conversation.id,
#     extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
# )

# print(f"Response output: {response.output_text}")

# # After an inactivity in the conversation, memories will be extracted
# # from the conversation and stored
# print("Waiting for memories to be stored...")
# time.sleep(65)

# # -----------------------------------------------------------------------
# # 4. New conversation – the agent should recall the preference
# # -----------------------------------------------------------------------

# # Create a new conversation
# new_conversation = openai_client.conversations.create()
# print(f"Created new conversation (id: {new_conversation.id})")

# # Create an agent response with stored memories
# new_response = openai_client.responses.create(
#     input="Please order my usual coffee",
#     conversation=new_conversation.id,
#     extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
# )

# print(f"Response output: {new_response.output_text}")




if __name__ == "__main__":
    from agent_framework_devui import serve

    serve(entities=[agent, agent2], port=8090, auto_open=True)
    