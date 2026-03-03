import time

import os
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions, PromptAgentDefinition, MemorySearchTool
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

project_client = AIProjectClient(
    endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

memory_store_name = "my_memory_store"

# Specify memory store options
options = MemoryStoreDefaultOptions(
    chat_summary_enabled=True,
    user_profile_enabled=True,
    user_profile_details="Avoid irrelevant or sensitive data, such as age, financials, precise location, and credentials"
)

# Create memory store
definition = MemoryStoreDefaultDefinition(
    chat_model=os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"],  # Your chat model deployment name
    embedding_model="text-embedding-3-small",  # Your embedding model deployment name
    options=options
)

try:
    project_client.memory_stores.delete(memory_store_name)
    print(f"Memory store `{memory_store_name}` deleted")
except:
        pass

memory_store = project_client.memory_stores.create(
    name=memory_store_name,
    definition=definition,
    description="Memory store for customer support agent",
)

print(f"Created memory store: {memory_store.name}")



# Set scope to associate the memories with
# You can also use "{{$userId}}" to take the TID and OID of the request authentication header
scope = "user_123"

openai_client = project_client.get_openai_client()

# Create memory search tool
tool = MemorySearchTool(
    memory_store_name=memory_store_name,
    scope=scope,
    update_delay=1,  # Wait 1 second of inactivity before updating memories
    # In a real application, set this to a higher value like 300 (5 minutes, default)
)

# Create a prompt agent with memory search tool
agent = project_client.agents.create_version(
    agent_name="MyAgent",
    definition=PromptAgentDefinition(
        model=os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"],
        instructions="You are a helpful assistant that answers general questions",
        tools=[tool],
    )
)

print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")

# Create a conversation with the agent with memory tool enabled
conversation = openai_client.conversations.create()
print(f"Created conversation (id: {conversation.id})")

# Create an agent response to initial user message
response = openai_client.responses.create(
    input="I prefer dark roast coffee",
    conversation=conversation.id,
    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
)

print(f"Response output: {response.output_text}")

# After an inactivity in the conversation, memories will be extracted from the conversation and stored
print("Waiting for memories to be stored...")
time.sleep(65)

# Create a new conversation
new_conversation = openai_client.conversations.create()
print(f"Created new conversation (id: {new_conversation.id})")

# Create an agent response with stored memories
new_response = openai_client.responses.create(
    input="Please order my usual coffee",
    conversation=new_conversation.id,
    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
)

print(f"Response output: {new_response.output_text}")