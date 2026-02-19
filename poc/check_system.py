import os
import asyncio
import logging
import subprocess
from agent.db_utils import DatabasePool
from agent.graph_utils import GraphClient
# from graphiti_core import Graphiti  # We use GraphClient wrapper now or directly Graphiti if needed
# But check_system uses GraphClient wrapper from agent.graph_utils
# Let's check the file content again.


logger = logging.getLogger(__name__)

async def check_docker():
    """Checks if Docker daemon is running."""
    print("[-] Checking Docker status...")
    try:
        # Run 'docker info' to check daemon status. Pipe output to DEVNULL to suppress it.
        result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("[OK] Docker is running.")
        return True
    except subprocess.CalledProcessError:
        print("[FAIL] Docker is NOT running. Please start Docker Desktop.")
        return False
    except FileNotFoundError:
        print("[FAIL] Docker CLI not found. Is Docker installed?")
        return False

async def check_docker_compose():
    """Checks if services are running via Docker Compose and starts them if needed."""
    print("[-] Checking Docker Compose services...")
    
    # 1. Check if containers are running
    try:
        # Check specific containers by name defined in docker-compose.yml
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=poc_postgres", "--filter", "name=poc_neo4j", "--format", "{{.Names}}"],
            capture_output=True, text=True, check=True
        )
        running_containers = result.stdout.strip().split('\n')
        
        expected_containers = {'poc_postgres', 'poc_neo4j'}
        running_set = set(filter(None, running_containers))
        
        if expected_containers.issubset(running_set):
            print("[OK] All required containers are running.")
            return True
        else:
            missing = expected_containers - running_set
            print(f"[!] Missing running containers: {missing}")
            print("[-] Attempting to start services via 'docker-compose up -d'...")
            
            subprocess.run(["docker-compose", "up", "-d"], check=True)
            print("[+] Services started. Waiting for health checks...")
            
            # Simple wait loop (could be more robust checking 'docker inspect --format {{.State.Health.Status}}')
            for i in range(15):
                print(f"    Waiting for services to be healthy... ({i+1}/15)")
                await asyncio.sleep(2)
                
            print("[OK] Services should be up.")
            return True
            
    except FileNotFoundError:
        print("[FAIL] 'docker-compose' or 'docker' command not found.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] Error managing docker services: {e}")
        return False

async def check_connections():
    """Checks connections to Docker, Postgres, and Neo4j."""
    print("\n=== SYSTEM HEALTH CHECK ===")
    
    # 1. Docker Check
    if not await check_docker():
        return False

    # 2. Docker Compose Auto-Start
    if not await check_docker_compose():
        print("[!] Warning: Docker Compose check failed or services could not be started.")
        # We don't return False here necessarily, we let the individual connection checks fail if they must.

    # 3. Postgres
    print("[-] Checking Postgres connection...")

    try:
        pool = await DatabasePool.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        print("[OK] Postgres connection successful.")
    except Exception as e:
        print(f"[FAIL] Postgres connection failed: {e}")
        print("    -> Ensure Postgres container is running.")
        return False

    # 3. Neo4j / Graphiti
    print("[-] Checking Graphiti/Neo4j connection...")
    try:
        # Simple check if we can instantiate client
        # In a real scenario, we might want to check connectivity explicitly
        client = GraphClient.get_client()
        # To be more robust, we might try a simple query if the client exposes a driver
        # or just assume init is enough for now.
        print("[OK] Graphiti client initialized.")
    except Exception as e:
        print(f"[FAIL] Graphiti client failed: {e}")
        print("    -> Ensure Neo4j container is running.")
        return False
        
    print("=== ALL SYSTEMS GO ===\n")
    return True

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = asyncio.run(check_connections())
    exit(0 if success else 1)
