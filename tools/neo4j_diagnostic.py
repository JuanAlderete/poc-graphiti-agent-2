"""
Neo4j Diagnostic Script
-----------------------
Queries Neo4j to show everything stored: nodes, relationships, episodes.
Run: python -m tools.neo4j_diagnostic
"""

import asyncio
import os
import sys

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
import neo4j
from neo4j import AsyncGraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


async def run_diagnostic():
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=neo4j.basic_auth(NEO4J_USER, NEO4J_PASSWORD))

    async with driver.session(database="neo4j") as session:
        print("=" * 60)
        print("NEO4J DIAGNOSTIC REPORT")
        print("=" * 60)

        result = await session.run("MATCH (n) RETURN count(n) AS total")
        record = await result.single()
        print(f"\nTotal nodes: {record['total']}")

        result = await session.run("MATCH ()-[r]->() RETURN count(r) AS total")
        record = await result.single()
        print(f"Total relationships: {record['total']}")

        # Node types breakdown
        print("\n" + "-" * 40)
        print("NODE LABELS BREAKDOWN")
        print("-" * 40)
        result = await session.run(
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS count ORDER BY count DESC"
        )
        records = [r async for r in result]
        for r in records:
            print(f"  {r['label']:30s} -> {r['count']}")

        # Relationship types
        print("\n" + "-" * 40)
        print("RELATIONSHIP TYPES")
        print("-" * 40)
        result = await session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC"
        )
        records = [r async for r in result]
        for r in records:
            print(f"  {r['type']:30s} -> {r['count']}")

        # Episodic nodes (documents ingested)
        print("\n" + "-" * 40)
        print("EPISODIC NODES (ingested documents)")
        print("-" * 40)
        result = await session.run(
            "MATCH (e) WHERE 'Episodic' IN labels(e) "
            "RETURN e.name AS name, e.created_at AS created, e.group_id AS group_id "
            "ORDER BY e.created_at"
        )
        records = [r async for r in result]
        if records:
            for r in records:
                print(f"  [DOC] {str(r['name'] or '(unnamed)'):30s}  created={r['created']}  group={r['group_id']}")
        else:
            print("  (none found)")

        # Entity nodes
        print("\n" + "-" * 40)
        print("ENTITY NODES (top 30)")
        print("-" * 40)
        result = await session.run(
            "MATCH (e:Entity) "
            "RETURN e.name AS name, e.uuid AS uuid, e.summary AS summary "
            "ORDER BY e.name LIMIT 30"
        )
        records = [r async for r in result]
        if records:
            for r in records:
                summary = (r['summary'] or '')[:80]
                print(f"  [E] {str(r['name'] or '?'):25s}  {summary}")
        else:
            print("  (none found)")

        # Sample relationships with names
        print("\n" + "-" * 40)
        print("SAMPLE EDGES (top 20)")
        print("-" * 40)
        result = await session.run(
            "MATCH (a)-[r]->(b) WHERE 'Entity' IN labels(a) AND 'Entity' IN labels(b) "
            "RETURN a.name AS from_name, type(r) AS rel, b.name AS to_name, "
            "r.fact AS fact "
            "LIMIT 20"
        )
        records = [r async for r in result]
        if records:
            for r in records:
                fact = (r['fact'] or '')[:60]
                print(f"  {r['from_name']} --[{r['rel']}]--> {r['to_name']}")
                if fact:
                    print(f"    Fact: {fact}")
        else:
            print("  (none found)")

    await driver.close()
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(run_diagnostic())
