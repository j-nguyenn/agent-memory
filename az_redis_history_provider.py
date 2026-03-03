# Copyright (c) Microsoft. All rights reserved.

"""Azure Managed Redis History Provider with Azure AD Authentication - Interactive Mode

This example demonstrates how to use Azure Managed Redis with Azure AD authentication
to persist conversational details using RedisHistoryProvider in an interactive chat session.

Requirements:
  - Azure Managed Redis instance with Azure AD authentication enabled
  - Azure credentials configured (az login or managed identity)
  - agent-framework-redis: pip install agent-framework-redis
  - azure-identity: pip install azure-identity

Environment Variables:
  - REDIS_HOST: Your Azure Managed Redis host (e.g., myredis.redis.cache.windows.net)
  - AZURE_AI_PROJECT_ENDPOINT: Your Azure AI Foundry project endpoint
  - AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME: Azure OpenAI Responses deployment name
  - USER_OBJECT_ID: Your Azure AD User Object ID for authentication
"""

import asyncio
import os
import logging
from agent_framework.azure import AzureOpenAIResponsesClient
from agent_framework.redis import RedisHistoryProvider
from azure.identity import AzureCliCredential
from azure.identity.aio import AzureCliCredential as AsyncAzureCliCredential
from redis.credentials import CredentialProvider


class AzureCredentialProvider(CredentialProvider):
    """Credential provider for Azure AD authentication with Redis Enterprise."""

    def __init__(self, azure_credential: AsyncAzureCliCredential, user_object_id: str):
        self.azure_credential = azure_credential
        self.user_object_id = user_object_id

    async def get_credentials_async(self) -> tuple[str] | tuple[str, str]:
        """Get Azure AD token for Redis authentication.

        Returns (username, token) where username is the Azure user's Object ID.
        """
        token = await self.azure_credential.get_token("https://redis.azure.com/.default")
        return (self.user_object_id, token.token)


async def main() -> None:
    redis_host = os.getenv("REDIS_HOST", "")	
    user_object_id = os.getenv("USER_OBJECT_ID", "")

    # Create Azure CLI credential provider (uses 'az login' credentials)
    azure_credential = AsyncAzureCliCredential()
    credential_provider = AzureCredentialProvider(azure_credential, user_object_id)

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

    # Create chat client
    client = AzureOpenAIResponsesClient(
        project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        deployment_name=os.environ["AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME"],
        credential=AzureCliCredential(),
    )

    # Create agent with Azure Redis history provider
    agent = client.as_agent(
        name="AzureRedisAssistant",
        instructions="You are a helpful assistant.",
        context_providers=[history_provider],
    )

    print("=" * 60)
    print("Azure Redis Chat Assistant - Interactive Mode")
    print("=" * 60)
    print("Type your messages below. Commands:")
    print("  - 'quit' or 'exit' to end the conversation")
    print("  - 'clear' to clear the screen")
    print("=" * 60)
    print()

    # Interactive conversation loop
    try:
        while True:
            # Get user input
            try:
                user_input = input("You: ").strip()
            except EOFError:
                print("\nGoodbye!")
                break

            # Handle empty input
            if not user_input:
                continue

            # Handle commands
            if user_input.lower() in ['quit', 'exit']:
                print("Goodbye!")
                break
            
            if user_input.lower() == 'clear':
                os.system('clear' if os.name == 'posix' else 'cls')
                continue

            # Send message to agent and get response
            try:
                result = await agent.run(user_input)
                print(f"Assistant: {result}")
                print()
            except Exception as e:
                print(f"Error: {e}")
                print()

    except KeyboardInterrupt:
        print("\n\nConversation interrupted. Goodbye!")
    finally:
        # Cleanup
        await azure_credential.close()


if __name__ == "__main__":
    asyncio.run(main())