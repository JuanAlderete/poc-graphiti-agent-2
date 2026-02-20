import asyncio
import os
import time

import nest_asyncio
import pandas as pd
import streamlit as st

# FIXED: patch the event loop so asyncio.run / await work inside Streamlit
nest_asyncio.apply()

from agent.db_utils import DatabasePool, get_document_summary
from agent.tools import graph_search_tool, hybrid_search_tool, vector_search_tool
from poc.content_generator import get_content_generator
from poc.logging_utils import (
    GENERATION_LOG_PATH,
    INGESTION_LOG_PATH,
    SEARCH_LOG_PATH,
    clear_all_logs,
    generation_logger,
    ingestion_logger,
    search_logger,
)
from poc.prompts import email, historia, reel_cta
from poc.run_poc import run_ingestion
from poc.hydrate_graph import hydrate_graph

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Graphiti POC Dashboard",
    page_icon="🕸️",
    layout="wide",
)
st.title("🕸️ Graphiti POC — Agentic Control Centre")


# ---------------------------------------------------------------------------
# Helper: run async coroutines safely inside Streamlit
# ---------------------------------------------------------------------------

def run_async(coro):
    """Run an async coroutine from sync Streamlit context."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_log(filename: str) -> pd.DataFrame:
    path = os.path.join("logs", filename)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            pass
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Configuration")
    provider = os.getenv("LLM_PROVIDER", "openai").upper()
    st.info(f"LLM Provider: **{provider}**")
    st.divider()

    st.subheader("Actions")
    if st.button("🗑️ Clear Logs & DB", type="primary"):
        clear_all_logs()
        run_async(DatabasePool.clear_database())  # FIXED: use run_async
        st.success("Logs and Database Cleared!")
        time.sleep(0.8)
        st.rerun()

    if st.button("💧 Re-hydrate Graph (Force)", help="Push all docs to Neo4j"):
        with st.spinner("Hydrating Graph from Postgres..."):
            try:
                run_async(hydrate_graph(reset_flags=True))
                st.success("Hydration Complete!")
            except Exception as e:
                st.error(f"Error: {e}")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_ingest, tab_kb, tab_search, tab_gen, tab_analytics, tab_projections = st.tabs([
    "📥 Ingestion",
    "🧠 Knowledge Base",
    "🔍 Search",
    "✨ Generation",
    "📊 Analytics",
    "📈 Proyecciones",
])


# ── TAB 1: INGESTION ────────────────────────────────────────────────────────
with tab_ingest:
    st.header("Document Ingestion")

    col1, col2 = st.columns([3, 1])
    with col1:
        docs_dir = st.text_input("Directory Path", value="documents_to_index")
    with col2:
        skip_graphiti = st.checkbox(
            "Skip Graphiti (Postgres only)", value=True, help="Faster — vector search only."
        )

    if st.button("▶ Start Ingestion"):
        if not os.path.exists(docs_dir):
            st.error(f"Directory '{docs_dir}' not found.")
        else:
            with st.status("Ingesting documents…", expanded=True) as status:
                st.write("Initialising pipeline…")
                try:
                    run_async(run_ingestion(docs_dir, skip_graphiti=skip_graphiti))
                    status.update(label="Ingestion Complete!", state="complete", expanded=False)
                    st.success(f"Successfully ingested documents from `{docs_dir}`.")
                except Exception as exc:
                    status.update(label="Ingestion Failed", state="error")
                    st.error(f"Error: {exc}")



# ── TAB 2: KNOWLEDGE BASE ───────────────────────────────────────────────────
with tab_kb:
    st.header("🧠 Knowledge Base")
    if st.button("🔄 Refresh DB", key="refresh_kb"):
        st.rerun()

    try:
        docs = run_async(get_document_summary())
        if not docs:
            st.info("No documents found in database.")
        else:
            df_docs = pd.DataFrame(docs)
            # Display metrics
            total_docs = len(df_docs)
            total_chunks = df_docs["chunk_count"].sum() if "chunk_count" in df_docs.columns else 0
            
            c1, c2 = st.columns(2)
            c1.metric("Total Documents", total_docs)
            c2.metric("Total Chunks", total_chunks)
            
            st.divider()
            
            # Search filter
            filter_txt = st.text_input("Filter by filename/title", "", key="kb_filter")
            if filter_txt:
                df_docs = df_docs[
                    df_docs["title"].str.contains(filter_txt, case=False, na=False) |
                    df_docs["filepath"].str.contains(filter_txt, case=False, na=False)
                ]

            st.dataframe(
                df_docs,
                column_config={
                    "created_at": st.column_config.DatetimeColumn("Ingested At", format="D MMM YYYY, h:mm a"),
                    "metadata": st.column_config.Column("Metadata"),
                    "chunk_count": st.column_config.NumberColumn("Chunks"),
                    "filepath": st.column_config.TextColumn("File Path"),
                    "title": st.column_config.TextColumn("Title"),
                },
                use_container_width=True,
                hide_index=True,
            )
    except Exception as e:
        st.error(f"Error fetching knowledge base: {e}")


# ── TAB 3: SEARCH ───────────────────────────────────────────────────────────

with tab_search:
    st.header("Graph & Vector Search")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_area("Search Query", "Estrategias de crecimiento para startups B2B")
    with col2:
        search_type = st.radio("Search Type", ["Vector", "Graph", "Hybrid"], index=2)

    if st.button("🔍 Run Search"):
        with st.spinner(f"Running {search_type} search…"):
            try:
                if search_type == "Vector":
                    results = run_async(vector_search_tool(query))
                elif search_type == "Graph":
                    results = run_async(graph_search_tool(query))
                else:
                    results = run_async(hybrid_search_tool(query))

                st.subheader(f"{len(results)} result(s)")
                
                # Debug Mode Toggle
                debug_mode = st.checkbox("Show Raw JSON (Debug Mode)", value=False)

                for i, r in enumerate(results, 1):
                    with st.expander(f"#{i} — score {r.score:.3f} [{r.source}]"):
                        st.markdown(r.content)
                        if debug_mode:
                             st.caption("Raw Result Data:")
                             st.json(r.__dict__)
                        elif r.metadata:
                            st.caption("Metadata:")
                            st.json(r.metadata)
            except Exception as exc:
                st.error(f"Search failed: {exc}")


# ── TAB 3: GENERATION ───────────────────────────────────────────────────────
with tab_gen:
    st.header("Content Generation")

    template_type = st.selectbox("Select Template", ["Cold Email", "Startup Story", "Instagram Reel", "Custom"])

    prompt = system_prompt = ""
    formato = "text"

    if template_type == "Cold Email":
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("Topic", "SaaS Growth")
            objective = st.text_input("Objective", "Agendar una demo")
        with col2:
            context = st.text_area("Context", "Contexto simulado sobre crecimiento B2B…")
        system_prompt = email.SYSTEM_PROMPT
        prompt = email.PROMPT_TEMPLATE.format(topic=topic, context=context, objective=objective)
        formato = "email"

    elif template_type == "Startup Story":
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("Topic", "El origen de una startup")
            tone = st.text_input("Tone", "Inspirador")
        with col2:
            context = st.text_area("Context", "Fundadores en un garaje…", height=100)
        system_prompt = historia.SYSTEM_PROMPT
        prompt = historia.PROMPT_TEMPLATE.format(topic=topic, context=context, tone=tone)
        formato = "historia"

    elif template_type == "Instagram Reel":
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("Topic", "Productivity Hacks")
            cta = st.text_input("CTA", "Sígueme para más")
        with col2:
            context = st.text_input("Context", "Uso de herramientas AI…")
        system_prompt = reel_cta.SYSTEM_PROMPT
        prompt = reel_cta.PROMPT_TEMPLATE.format(topic=topic, context=context, cta=cta)
        formato = "reel_cta"

    elif template_type == "Custom":
        topic = st.text_input("Topic/Title", "Mi Nuevo Contenido")
        system_prompt = st.text_area("System Prompt", "Eres un experto en marketing digital.")
        prompt = st.text_area("Prompt", "Escribe un post sobre...", height=150)
        formato = "custom"

    if st.button("✨ Generate Content"):
        with st.spinner("Generating…"):
            try:
                generator = get_content_generator()
                # FIXED: pass formato/tema to generator for accurate logs
                content = run_async(
                    generator.generate(prompt, system_prompt, formato=formato, tema=topic)
                )
                st.subheader("Generated Content")
                st.markdown(content)
                st.divider()
                st.caption(f"Generated using **{provider}**")
            except Exception as exc:
                st.error(f"Generation failed: {exc}")


# ── TAB 4: ANALYTICS ────────────────────────────────────────────────────────
with tab_analytics:
    st.header("System Analytics")
    if st.button("🔄 Refresh"):
        st.rerun()

    df_ingest = load_log("ingesta_log.csv")
    df_search = load_log("busqueda_log.csv")
    df_gen = load_log("generacion_log.csv")

    # Overview metrics
    total_cost = 0.0
    if not df_ingest.empty and "costo_total_usd" in df_ingest.columns:
        total_cost += df_ingest["costo_total_usd"].sum()
    if not df_gen.empty and "costo_usd" in df_gen.columns:
        total_cost += df_gen["costo_usd"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Cost (Est)", f"${total_cost:.4f}")
    c2.metric("Files Ingested", len(df_ingest) if not df_ingest.empty else 0)
    c3.metric("Searches Run", len(df_search) if not df_search.empty else 0)
    c4.metric("Pieces Generated", len(df_gen) if not df_gen.empty else 0)
    st.divider()

    st.divider()

    st.subheader("Cost Evolution")
    cost_data = []
    if not df_ingest.empty and "timestamp" in df_ingest.columns:
        for _, r in df_ingest.iterrows():
            cost_data.append({"time": r["timestamp"], "cost": r.get("costo_total_usd", 0), "type": "Ingestion"})
    if not df_search.empty and "timestamp" in df_search.columns:
        for _, r in df_search.iterrows():
            cost_data.append({"time": r["timestamp"], "cost": r.get("costo_total_usd", 0), "type": "Search"})
    if not df_gen.empty and "timestamp" in df_gen.columns:
        for _, r in df_gen.iterrows():
            cost_data.append({"time": r["timestamp"], "cost": r.get("costo_usd", 0), "type": "Generation"})
            
    if cost_data:
        df_cost = pd.DataFrame(cost_data)
        df_cost["time"] = pd.to_datetime(df_cost["time"], unit="s")
        st.scatter_chart(df_cost, x="time", y="cost", color="type")
    else:
        st.info("No cost data to display.")

    st.divider()

    log1, log2, log3 = st.tabs(["Ingestion Log", "Search Log", "Generation Log"])

    with log1:
        if not df_ingest.empty:
            st.dataframe(df_ingest, use_container_width=True)
            if "tiempo_seg" in df_ingest.columns and "nombre_archivo" in df_ingest.columns:
                st.bar_chart(df_ingest.set_index("nombre_archivo")["tiempo_seg"])
        else:
            st.info("No ingestion logs yet.")

    with log2:
        if not df_search.empty:
            st.dataframe(df_search, use_container_width=True)
            if "latencia_ms" in df_search.columns and "tipo_busqueda" in df_search.columns:
                st.bar_chart(df_search.groupby("tipo_busqueda")["latencia_ms"].mean())
        else:
            st.info("No search logs yet.")

    with log3:
        if not df_gen.empty:
            st.dataframe(df_gen, use_container_width=True)
            if "tokens_out" in df_gen.columns and "tiempo_seg" in df_gen.columns:
                st.scatter_chart(df_gen, x="tokens_out", y="tiempo_seg", color="modelo")
        else:
            st.info("No generation logs yet.")


# ── TAB 5: PROYECCIONES ─────────────────────────────────────────────────────
with tab_projections:
    st.header("📈 Proyecciones de Costo")
    st.caption("Ajustá los parámetros para simular distintos escenarios de uso.")

    col1, col2, col3 = st.columns(3)
    with col1:
        docs_per_month = st.number_input("Documentos / mes", min_value=1, value=250, step=10)
    with col2:
        queries_per_month = st.number_input("Búsquedas / mes", min_value=0, value=5000, step=100)
    with col3:
        pieces_per_month = st.number_input("Piezas generadas / mes", min_value=0, value=200, step=10)

    # Use averages from logs if available, else fallback defaults
    avg_ingest_cost = (
        df_ingest["costo_total_usd"].mean()
        if not df_ingest.empty and "costo_total_usd" in df_ingest.columns
        else 0.05
    )
    avg_search_cost = (
        df_search["costo_total_usd"].mean()
        if not df_search.empty and "costo_total_usd" in df_search.columns
        else 0.0002
    )
    avg_gen_cost = (
        df_gen["costo_usd"].mean()
        if not df_gen.empty and "costo_usd" in df_gen.columns
        else 0.003
    )

    monthly_ingest = docs_per_month * avg_ingest_cost
    monthly_search = queries_per_month * avg_search_cost
    monthly_gen = pieces_per_month * avg_gen_cost
    monthly_total = monthly_ingest + monthly_search + monthly_gen
    annual_total = monthly_total * 12

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ingesta / mes", f"${monthly_ingest:.2f}")
    c2.metric("Búsquedas / mes", f"${monthly_search:.2f}")
    c3.metric("Generación / mes", f"${monthly_gen:.2f}")
    c4.metric("**Total / mes**", f"${monthly_total:.2f}")

    st.metric("💰 Costo anual proyectado", f"${annual_total:.2f}")

    # Decision badge
    st.divider()
    if monthly_total < 100:
        st.success("✅ **GO** — Costo mensual por debajo del umbral de $100")
    elif monthly_total < 200:
        st.warning("⚠️ **OPTIMIZE** — Costo entre $100–$200/mes. Revisar oportunidades.")
    else:
        st.error("🛑 **STOP** — Costo superior a $200/mes. Arquitectura no viable.")

    with st.expander("Ver costos unitarios usados"):
        st.write(
            {
                "avg_ingest_cost_usd": round(avg_ingest_cost, 6),
                "avg_search_cost_usd": round(avg_search_cost, 6),
                "avg_generation_cost_usd": round(avg_gen_cost, 6),
                "source": "from logs" if not df_ingest.empty else "default estimates",
            }
        )