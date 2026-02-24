"""Quick diagnostic: count Neo4j nodes, rels and list episodes."""
from poc.config import config
from neo4j import GraphDatabase
import neo4j

d = GraphDatabase.driver(config.NEO4J_URI, auth=neo4j.basic_auth(config.NEO4J_USER, config.NEO4J_PASSWORD))
with d.session(database="neo4j") as s:
    n_nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    n_rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    labels = s.run("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c ORDER BY c DESC").data()
    episodes = s.run(
        "MATCH (e) WHERE 'Episodic' IN labels(e) "
        "RETURN e.name AS name, e.group_id AS group ORDER BY e.created_at"
    ).data()

print(f"\n=== Neo4j Diagnostic ===")
print(f"Nodos totales  : {n_nodes}")
print(f"Relaciones     : {n_rels}")
print(f"\nLabels:")
for lb in labels:
    print(f"  {lb['l']:<20} {lb['c']}")
print(f"\nEpisodios ({len(episodes)}):")
for ep in episodes:
    print(f"  - {ep['name']}  [group: {ep['group']}]")
d.close()
