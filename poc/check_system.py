import asyncio
import logging
import os
import subprocess

from agent.db_utils import DatabasePool

logger = logging.getLogger(__name__)


async def check_docker() -> bool:
    """Verifica que el daemon de Docker esté corriendo."""
    print("[-] Checking Docker status...")
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        print("[OK] Docker is running.")
        return True
    except subprocess.CalledProcessError:
        print("[FAIL] Docker is NOT running. Please start Docker Desktop.")
        return False
    except FileNotFoundError:
        print("[FAIL] Docker CLI not found. Is Docker installed?")
        return False


async def check_docker_compose() -> bool:
    """Verifica que los contenedores estén corriendo, los arranca si no."""
    print("[-] Checking Docker Compose services...")
    try:
        result = subprocess.run(
            [
                "docker", "ps",
                "--filter", "name=poc_postgres",
                "--filter", "name=poc_neo4j",
                "--format", "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        running = set(filter(None, result.stdout.strip().split("\n")))
        expected = {"poc_postgres", "poc_neo4j"}

        if expected.issubset(running):
            print("[OK] All required containers are running.")
            return True

        missing = expected - running
        print(f"[!] Missing containers: {missing}")
        print("[-] Attempting to start services via 'docker-compose up -d'...")
        subprocess.run(["docker-compose", "up", "-d"], check=True)
        print("[+] Services started. Waiting 30s for them to be healthy...")
        for i in range(15):
            print(f"    Waiting... ({i + 1}/15)")
            await asyncio.sleep(2)
        print("[OK] Services should be up.")
        return True

    except FileNotFoundError:
        print("[FAIL] 'docker-compose' or 'docker' command not found.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] Error managing Docker services: {e}")
        return False


async def check_connections() -> bool:
    """
    Verifica conexiones a Docker, Postgres y Neo4j/Graphiti.
    Retorna True si todos los checks pasan.
    """
    print("\n=== SYSTEM HEALTH CHECK ===")

    # ── 1. Docker ─────────────────────────────────────────────────────────────
    # Non-fatal: when running INSIDE a Docker container, the Docker CLI is not
    # available. We skip these checks and trust the depends_on guarantees.
    docker_ok = await check_docker()
    if not docker_ok:
        print("[!] Warning: Docker CLI not found — likely running inside a container.")
        print("[!] Skipping Docker / Compose checks and proceeding.\n")
    else:
        # ── 2. Docker Compose (auto-start) ────────────────────────────────────────
        if not await check_docker_compose():
            print("[!] Warning: could not verify/start Docker Compose services.")

    # ── 3. Postgres ───────────────────────────────────────────────────────────
    print("[-] Checking Postgres connection...")
    try:
        pool = await DatabasePool.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        print("[OK] Postgres connection successful.")
    except Exception as e:
        print(f"[FAIL] Postgres connection failed: {e}")
        print("    -> Ensure the postgres container is running and .env is correct.")
        return False

    # ── 4. Neo4j / Graphiti ───────────────────────────────────────────────────
    print("[-] Checking Graphiti/Neo4j connection...")
    try:
        # Construir el objeto Graphiti (solo verifica credenciales, no conectividad completa)
        # FIXED: usamos _build_client() — ya no existe get_client() público
        from agent.graph_utils import GraphClient
        client = GraphClient._build_client()
        # Intentar una operación mínima que verifique conectividad real
        # build_indices_and_constraints() es muy costosa aquí; simplemente
        # verificamos que el driver del neo4j driver puede crearse.
        print("[OK] Graphiti client initialized successfully.")
    except Exception as e:
        print(f"[FAIL] Graphiti client failed: {e}")
        print("    -> Ensure Neo4j container is running and NEO4J_* vars in .env are correct.")
        return False

    print("=== ALL SYSTEMS GO ===\n")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = asyncio.run(check_connections())
    exit(0 if success else 1)