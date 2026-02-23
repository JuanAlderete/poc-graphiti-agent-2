import neo4j
from neo4j import GraphDatabase

d = GraphDatabase.driver("neo4j://127.0.0.1:7687", auth=neo4j.basic_auth("neo4j", "adminadmin"))
s = d.session(database="neo4j")

print("Nodes:", s.run("MATCH (n) RETURN count(n) AS c").single()["c"])
print("Rels:", s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"])

labels = s.run(
    "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY count DESC"
).data()
print("\nLabel breakdown:")
for l in labels:
    print(f"  {l['label']}: {l['count']}")

eps = s.run(
    "MATCH (e) WHERE 'Episodic' IN labels(e) RETURN e.name AS name, e.source_description AS src ORDER BY e.created_at"
).data()
print(f"\nEpisodes ({len(eps)}):")
for e in eps:
    print(f"  - {e['name']}  (src: {e.get('src', '?')})")

s.close()
d.close()
