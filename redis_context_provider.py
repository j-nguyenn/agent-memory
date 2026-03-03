import os

from azure.identity import AzureCliCredential
from agent_framework.azure import AzureOpenAIResponsesClient
from agent_framework.redis import RedisContextProvider
from agent_framework_devui import serve
from dotenv import load_dotenv


def main() -> None:
	load_dotenv()

	redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
	session_id = os.getenv("SESSION_ID", "demo-session")

	client = AzureOpenAIResponsesClient(
		project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
		deployment_name=os.environ["AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME"],
		credential=AzureCliCredential(),
	)

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

	print("RedisContextProvider simple example")
	print(f"REDIS_URL={redis_url}")
	print(f"SESSION_ID={session_id}")

	
	print("Starting DevUI on http://localhost:8090")

	serve(entities=[agent], port=8090, auto_open=True)

if __name__ == "__main__":
	main()
