import os
import asyncio
from azure.identity import AzureCliCredential
from redis.credentials import CredentialProvider
import redis.asyncio as redis

"""
Redis Inspection Tool

Use this to check what's stored in your Azure Redis instance.
"""


class AzureCredentialProvider(CredentialProvider):
    """Credential provider for Azure AD authentication with Redis Enterprise."""

    def __init__(self, azure_credential: AzureCliCredential, user_object_id: str):
        self.azure_credential = azure_credential
        self.user_object_id = user_object_id

    async def get_credentials_async(self) -> tuple[str] | tuple[str, str]:
        """Get Azure AD token for Redis authentication."""
        token = self.azure_credential.get_token("https://redis.azure.com/.default")
        return (self.user_object_id, token.token)


async def inspect_redis():
    """Inspect what's stored in Redis."""
    redis_host = "memoryredis.uksouth.redis.azure.net"
    user_object_id = "31ea8a3f-1e3f-437d-949d-41ee02d3fa0b"
    credential = AzureCliCredential()
    credential_provider = AzureCredentialProvider(credential, user_object_id)
    
    # Create Redis connection
    r = await redis.Redis(
        host=redis_host,
        port=10000,
        ssl=True,
        credential_provider=credential_provider,
        decode_responses=True,
    )
    
    try:
        print("Connecting to Redis...")
        await r.ping()
        print("✓ Connected successfully!\n")
        
        # Get all keys (or filter by pattern)
        print("Searching for keys with pattern: chat_messages:*")
        keys = await r.keys("chat_messages:*")
        print(f"\n=== Found {len(keys)} keys ===\n")
        
        if not keys:
            print("No keys found. Try a different pattern or check all keys:")
            all_keys = await r.keys("*")
            print(f"Total keys in database: {len(all_keys)}")
            if all_keys:
                print("\nFirst 10 keys:")
                for key in all_keys[:10]:
                    print(f"  - {key}")
        
        for key in keys:
            print(f"\n{'='*60}")
            print(f"Key: {key}")
            print(f"{'='*60}")
            
            key_type = await r.type(key)
            print(f"Type: {key_type}")
            
            # Get TTL
            ttl = await r.ttl(key)
            if ttl > 0:
                print(f"TTL: {ttl} seconds")
            elif ttl == -1:
                print("TTL: No expiration")
            
            # Get value based on type
            if key_type == "string":
                value = await r.get(key)
                if len(value) > 500:
                    print(f"\nValue (truncated):\n{value[:500]}...\n")
                else:
                    print(f"\nValue:\n{value}\n")
                    
            elif key_type == "list":
                length = await r.llen(key)
                print(f"List length: {length}")
                items = await r.lrange(key, 0, -1)
                print("\nList items:")
                for i, item in enumerate(items):
                    if len(item) > 200:
                        print(f"  [{i}]: {item[:200]}...")
                    else:
                        print(f"  [{i}]: {item}")
                        
            elif key_type == "hash":
                hash_data = await r.hgetall(key)
                print(f"\nHash fields ({len(hash_data)} fields):")
                for field, value in hash_data.items():
                    if len(str(value)) > 200:
                        print(f"  {field}: {str(value)[:200]}...")
                    else:
                        print(f"  {field}: {value}")
                        
            elif key_type == "set":
                members = await r.smembers(key)
                print(f"\nSet members ({len(members)} items):")
                for member in members:
                    print(f"  - {member}")
                    
            elif key_type == "zset":
                members = await r.zrange(key, 0, -1, withscores=True)
                print(f"\nSorted set members ({len(members)} items):")
                for member, score in members:
                    print(f"  {member}: {score}")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await r.aclose()
        print("\n✓ Connection closed")


async def clear_redis_keys(pattern: str = "chat_messages:*"):
    """Clear keys matching a pattern (use with caution!)."""
    redis_host = "memoryredis.uksouth.redis.azure.net"
    user_object_id = "31ea8a3f-1e3f-437d-949d-41ee02d3fa0b"
    credential = AzureCliCredential()
    credential_provider = AzureCredentialProvider(credential, user_object_id)
    
    r = await redis.Redis(
        host=redis_host,
        port=10000,
        ssl=True,
        credential_provider=credential_provider,
        decode_responses=True,
    )
    
    try:
        keys = await r.keys(pattern)
        if keys:
            print(f"Found {len(keys)} keys matching '{pattern}'")
            confirm = input("Delete all these keys? (yes/no): ")
            if confirm.lower() == "yes":
                deleted = await r.delete(*keys)
                print(f"✓ Deleted {deleted} keys")
            else:
                print("Cancelled")
        else:
            print(f"No keys found matching '{pattern}'")
    finally:
        await r.aclose()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        pattern = sys.argv[2] if len(sys.argv) > 2 else "chat_messages:*"
        asyncio.run(clear_redis_keys(pattern))
    else:
        asyncio.run(inspect_redis())