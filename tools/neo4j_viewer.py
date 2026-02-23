"""
Neo4j Graph Visualizer — Streamlit + Pyvis
-------------------------------------------
Interactive graph explorer for Neo4j data.
Run:  streamlit run tools/neo4j_viewer.py
"""

import asyncio
import os
import tempfile

import streamlit as st
from dotenv import load_dotenv
import neo4j
from neo4j import GraphDatabase
from pyvis.network import Network

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# ── Color palette per label ──────────────────────────────────────────────────
LABEL_COLORS = {
    "Entity": "#4FC3F7",
    "Episodic": "#FF8A65",
    "Community": "#AED581",
}
DEFAULT_COLOR = "#B0BEC5"

EDGE_COLORS = {
    "RELATES_TO": "#78909C",
    "MENTIONS": "#FFB74D",
    "HAS_MEMBER": "#4DB6AC",
}
DEFAULT_EDGE_COLOR = "#90A4AE"


# ── Neo4j queries ────────────────────────────────────────────────────────────
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=neo4j.basic_auth(NEO4J_USER, NEO4J_PASSWORD))


def get_stats(driver):
    with driver.session(database="neo4j") as session:
        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

        labels = session.run(
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS count ORDER BY count DESC"
        ).data()

        rel_types = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC"
        ).data()

    return node_count, rel_count, labels, rel_types


def get_episodes(driver):
    with driver.session(database="neo4j") as session:
        return session.run(
            "MATCH (e) WHERE 'Episodic' IN labels(e) "
            "RETURN e.name AS name, e.created_at AS created, e.group_id AS group_id "
            "ORDER BY e.created_at"
        ).data()


def get_graph_data(driver, limit=150, label_filter=None):
    with driver.session(database="neo4j") as session:
        # Get nodes
        if label_filter and label_filter != "All":
            node_query = f"MATCH (n:{label_filter}) RETURN n, labels(n) AS labels LIMIT $limit"
        else:
            node_query = "MATCH (n) RETURN n, labels(n) AS labels LIMIT $limit"

        nodes_result = session.run(node_query, limit=limit).data()

        # Get relationships between fetched nodes
        if label_filter and label_filter != "All":
            rel_query = (
                f"MATCH (a:{label_filter})-[r]->(b) "
                "RETURN a, r, b, type(r) AS rel_type, labels(a) AS a_labels, labels(b) AS b_labels "
                "LIMIT $limit"
            )
        else:
            rel_query = (
                "MATCH (a)-[r]->(b) "
                "RETURN a, r, b, type(r) AS rel_type, labels(a) AS a_labels, labels(b) AS b_labels "
                "LIMIT $limit"
            )

        rels_result = session.run(rel_query, limit=limit * 2).data()

    return nodes_result, rels_result


def build_pyvis_graph(nodes_data, rels_data, height="700px", physics=True):
    net = Network(
        height=height,
        width="100%",
        bgcolor="#1a1a2e",
        font_color="white",
        directed=True,
        notebook=False,
    )

    # Physics settings
    if physics:
        net.force_atlas_2based(
            gravity=-50,
            central_gravity=0.01,
            spring_length=150,
            spring_strength=0.08,
            damping=0.4,
        )
    else:
        net.toggle_physics(False)

    seen_nodes = set()

    # Add nodes from relationships (to capture both sides)
    for rec in rels_data:
        a = rec["a"]
        b = rec["b"]
        a_labels = rec["a_labels"]
        b_labels = rec["b_labels"]

        for node, labels in [(a, a_labels), (b, b_labels)]:
            node_id = node.get("uuid") or node.get("name") or str(id(node))
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)

            primary_label = labels[0] if labels else "Unknown"
            color = LABEL_COLORS.get(primary_label, DEFAULT_COLOR)
            name = node.get("name") or node.get("uuid", "?")[:12]
            summary = node.get("summary", "") or ""

            title = f"<b>{name}</b><br>Label: {primary_label}<br>"
            if summary:
                title += f"Summary: {summary[:200]}"

            size = 25 if primary_label == "Episodic" else 18 if primary_label == "Entity" else 15

            net.add_node(
                node_id,
                label=str(name)[:30],
                title=title,
                color=color,
                size=size,
                font={"size": 12, "color": "white"},
            )

    # Also add standalone nodes not in relationships
    for rec in nodes_data:
        node = rec["n"]
        labels = rec["labels"]
        node_id = node.get("uuid") or node.get("name") or str(id(node))
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)

        primary_label = labels[0] if labels else "Unknown"
        color = LABEL_COLORS.get(primary_label, DEFAULT_COLOR)
        name = node.get("name") or node.get("uuid", "?")[:12]

        net.add_node(
            node_id,
            label=str(name)[:30],
            title=f"<b>{name}</b><br>Label: {primary_label}",
            color=color,
            size=15,
            font={"size": 12, "color": "white"},
        )

    # Add edges
    for rec in rels_data:
        a = rec["a"]
        b = rec["b"]
        rel_type = rec["rel_type"]

        a_id = a.get("uuid") or a.get("name") or str(id(a))
        b_id = b.get("uuid") or b.get("name") or str(id(b))

        if a_id not in seen_nodes or b_id not in seen_nodes:
            continue

        edge_color = EDGE_COLORS.get(rel_type, DEFAULT_EDGE_COLOR)
        fact = rec["r"].get("fact", "") or ""

        title = f"<b>{rel_type}</b>"
        if fact:
            title += f"<br>{fact[:200]}"

        net.add_edge(
            a_id, b_id,
            title=title,
            label=rel_type[:20],
            color=edge_color,
            arrows="to",
            font={"size": 8, "color": "#aaa"},
        )

    return net


# ── Streamlit UI ─────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Neo4j Graph Explorer",
        page_icon="🔵",
        layout="wide",
    )

    st.markdown("""
    <style>
        .stApp { background-color: #0e0e1a; }
        .stat-card {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }
        .stat-number { font-size: 2.5rem; font-weight: 700; color: #4FC3F7; }
        .stat-label { font-size: 0.9rem; color: #90A4AE; margin-top: 4px; }
    </style>
    """, unsafe_allow_html=True)

    st.title("Neo4j Graph Explorer")
    st.caption(f"Connected to: `{NEO4J_URI}`")

    try:
        driver = get_driver()
        driver.verify_connectivity()
    except Exception as e:
        st.error(f"Cannot connect to Neo4j: {e}")
        return

    # ── Stats ────────────────────────────────────────────────────────────────
    node_count, rel_count, labels, rel_types = get_stats(driver)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{node_count}</div>
            <div class="stat-label">Nodes</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{rel_count}</div>
            <div class="stat-label">Relationships</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        episode_count = next((l["count"] for l in labels if l["label"] == "Episodic"), 0)
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{episode_count}</div>
            <div class="stat-label">Episodes</div>
        </div>""", unsafe_allow_html=True)

    # ── Sidebar controls ─────────────────────────────────────────────────────
    st.sidebar.header("Controls")

    label_options = ["All"] + [l["label"] for l in labels]
    label_filter = st.sidebar.selectbox("Filter by label", label_options)

    max_nodes = st.sidebar.slider("Max nodes", 10, 500, 100)
    enable_physics = st.sidebar.checkbox("Enable physics", True)

    if st.sidebar.button("Refresh", type="primary"):
        st.rerun()

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab_graph, tab_episodes, tab_details, tab_query = st.tabs(
        ["Graph", "Episodes", "Details", "Custom Query"]
    )

    # ── Graph Tab ────────────────────────────────────────────────────────────
    with tab_graph:
        if node_count == 0:
            st.warning("No nodes in database. Run ingestion first.")
        else:
            with st.spinner("Building graph..."):
                nodes_data, rels_data = get_graph_data(driver, limit=max_nodes, label_filter=label_filter)
                net = build_pyvis_graph(nodes_data, rels_data, physics=enable_physics)

                # Save to temp file and render
                with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as f:
                    net.save_graph(f.name)
                    with open(f.name, "r", encoding="utf-8") as html_file:
                        html_content = html_file.read()
                    st.components.v1.html(html_content, height=720, scrolling=False)

            st.caption(f"Showing {len(nodes_data)} nodes, {len(rels_data)} relationships")

    # ── Episodes Tab ─────────────────────────────────────────────────────────
    with tab_episodes:
        episodes = get_episodes(driver)
        if episodes:
            st.subheader(f"Ingested Episodes ({len(episodes)})")
            for ep in episodes:
                with st.expander(f"{ep['name'] or 'unnamed'}", expanded=False):
                    st.json(ep)
        else:
            st.info("No episodic nodes found.")

    # ── Details Tab ──────────────────────────────────────────────────────────
    with tab_details:
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Node Labels")
            for l in labels:
                color = LABEL_COLORS.get(l["label"], DEFAULT_COLOR)
                st.markdown(
                    f'<span style="color:{color}; font-weight:600">{l["label"]}</span>: {l["count"]}',
                    unsafe_allow_html=True,
                )
        with col_b:
            st.subheader("Relationship Types")
            for r in rel_types:
                st.markdown(f'`{r["type"]}`: {r["count"]}')

    # ── Custom Query Tab ─────────────────────────────────────────────────────
    with tab_query:
        st.subheader("Run Cypher Query")
        default_query = "MATCH (n) RETURN n.name AS name, labels(n) AS labels LIMIT 25"
        query = st.text_area("Cypher", value=default_query, height=100)
        if st.button("Execute"):
            try:
                with driver.session(database="neo4j") as session:
                    result = session.run(query).data()
                if result:
                    st.dataframe(result, use_container_width=True)
                else:
                    st.info("Query returned no results.")
            except Exception as e:
                st.error(f"Query error: {e}")

    driver.close()


if __name__ == "__main__":
    main()
