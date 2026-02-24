import asyncio
import os
import tempfile
import time

import nest_asyncio
import pandas as pd
import streamlit as st
import neo4j
from neo4j import GraphDatabase
from pyvis.network import Network

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

tab_ingest, tab_kb, tab_search, tab_gen, tab_analytics, tab_projections, tab_neo4j = st.tabs([
    "📥 Ingestion",
    "🧠 Knowledge Base",
    "🔍 Search",
    "✨ Generation",
    "📊 Analytics",
    "📈 Proyecciones",
    "🔵 Neo4j Graph",
])


# ── TAB 1: INGESTION ────────────────────────────────────────────────────────
with tab_ingest:
    st.header("Document Ingestion")

    skip_graphiti_global = st.checkbox(
        "⚡ Skip Graphiti (Postgres only)",
        value=True,
        help="Más rápido — solo búsqueda vectorial. Destildá para construir el grafo también.",
    )

    # ── Modo 1: Subir archivos ───────────────────────────────────────────────
    st.subheader("📤 Subir archivos")
    uploaded_files = st.file_uploader(
        "Arrastrá o seleccioná archivos para indexar",
        type=["txt", "md", "csv", "pdf"],
        accept_multiple_files=True,
        help="Formatos soportados: .txt, .md, .csv, .pdf",
    )

    if uploaded_files:
        st.info(f"{len(uploaded_files)} archivo(s) seleccionado(s): {', '.join(f.name for f in uploaded_files)}")

        if st.button("▶ Indexar archivos subidos", type="primary"):
            # Guardar archivos en documents_to_index/ y ejecutar pipeline
            save_dir = "documents_to_index"
            os.makedirs(save_dir, exist_ok=True)
            saved_paths = []

            with st.status("Procesando archivos…", expanded=True) as upload_status:
                # 1. Guardar en disco
                st.write("💾 Guardando archivos…")
                for uf in uploaded_files:
                    dest = os.path.join(save_dir, uf.name)
                    try:
                        raw = uf.read()
                        # Intentar decodificar como texto; si falla (PDF binario), avisamos
                        try:
                            text = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            text = raw.decode("latin-1", errors="replace")
                        with open(dest, "w", encoding="utf-8") as fh:
                            fh.write(text)
                        saved_paths.append(dest)
                        st.write(f"  ✅ {uf.name} guardado")
                    except Exception as e:
                        st.write(f"  ❌ {uf.name}: {e}")

                if not saved_paths:
                    upload_status.update(label="Sin archivos válidos", state="error")
                else:
                    # 2. Ingestar solo los archivos recién guardados
                    st.write(f"🔄 Indexando {len(saved_paths)} archivo(s)…")
                    try:
                        from ingestion.ingest import DocumentIngestionPipeline, ingest_files
                        run_async(ingest_files(saved_paths, skip_graphiti=skip_graphiti_global))
                        upload_status.update(label=f"✅ {len(saved_paths)} archivo(s) indexados", state="complete", expanded=False)
                        st.success(f"Indexación completada. Revisá el tab **Knowledge Base** para verificar.")
                    except Exception as exc:
                        upload_status.update(label="Error de indexación", state="error")
                        st.error(f"Error: {exc}")

    st.divider()

    # ── Modo 2: Directorio existente ─────────────────────────────────────────
    st.subheader("📁 Indexar directorio")
    col1, col2 = st.columns([3, 1])
    with col1:
        docs_dir = st.text_input("Ruta del directorio", value="documents_to_index")
    with col2:
        st.write("")  # spacer for alignment
        st.write("")

    if st.button("▶ Indexar directorio"):
        if not os.path.exists(docs_dir):
            st.error(f"Directorio '{docs_dir}' no encontrado.")
        else:
            with st.status("Ingesting documents…", expanded=True) as status:
                st.write("Initialising pipeline…")
                try:
                    run_async(run_ingestion(docs_dir, skip_graphiti=skip_graphiti_global))
                    status.update(label="Ingestion Complete!", state="complete", expanded=False)
                    st.success(f"Documentos indexados desde `{docs_dir}`.")
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
                width="stretch",
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

    # ── Sección: Agentes Estructurados (NUEVO) ─────────────────────────────────
    st.divider()
    st.subheader("🤖 Generación con Agentes Estructurados (Nuevo)")
    st.caption("Output estructurado por formato con campos específicos (Hook, Script, CTA, etc.)")

    col_fmt, col_topic = st.columns(2)
    with col_fmt:
        new_formato = st.selectbox(
            "Formato",
            ["reel_cta", "historia", "email", "reel_lead_magnet", "ads"],
            key="new_gen_formato"
        )
    with col_topic:
        new_topic = st.text_input("Tema", "Validación de ideas de negocio", key="new_gen_topic")

    new_context = st.text_area("Contexto (dejar vacío para búsqueda automática)", "", height=100, key="new_gen_context")

    extra_params = {}
    if new_formato == "reel_cta":
        extra_params["cta"] = st.text_input("CTA", "Sígueme para más", key="reel_cta_cta")
    elif new_formato == "historia":
        extra_params["tone"] = st.text_input("Tono", "Educativo y cercano", key="historia_tone")
        extra_params["tipo"] = st.selectbox("Tipo", ["educativa", "autoridad", "prueba_social", "cta"], key="historia_tipo")
    elif new_formato == "email":
        extra_params["objective"] = st.text_input("Objetivo", "Generar interés", key="email_obj")
    elif new_formato == "reel_lead_magnet":
        extra_params["lead_magnet"] = st.text_input("Lead Magnet", "Checklist gratuita", key="rlm_lm")
    elif new_formato == "ads":
        extra_params["tipo"] = st.selectbox("Tipo de anuncio", ["awareness", "consideration", "conversion"], key="ads_tipo")

    if st.button("🚀 Generar con Agente Estructurado"):
        with st.spinner(f"Generando {new_formato}…"):
            try:
                from services.generation_service import GenerationService
                from poc.budget_guard import get_budget_summary

                if not new_context:
                    results = run_async(hybrid_search_tool(new_topic, limit=3))
                    context_for_gen = "\n\n---\n\n".join(r.content for r in results) if results else "Sin contexto."
                else:
                    context_for_gen = new_context

                service = GenerationService()
                output = run_async(service.generate(new_formato, topic=new_topic, context=context_for_gen, **extra_params))

                # Budget summary
                budget = get_budget_summary()
                if budget["status"] == "critical":
                    st.warning(f"⚠️ Budget crítico: {budget['percentage']}% usado. Usando modelo fallback: {budget['active_model']}")
                elif budget["status"] == "warning":
                    st.info(f"💡 Budget al {budget['percentage']}%. Gasto: ${budget['spent_usd']} / ${budget['budget_usd']}")

                st.success(f"✅ QA {'PASSED' if output.qa_passed else 'FAILED'} | Costo: ${output.cost_usd:.4f}")

                if not output.qa_passed:
                    st.warning(f"QA notas: {output.qa_notes}")

                st.json(output.data)

            except Exception as exc:
                st.error(f"Error: {exc}")


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
            st.dataframe(df_ingest, width="stretch")
            if "tiempo_seg" in df_ingest.columns and "nombre_archivo" in df_ingest.columns:
                st.bar_chart(df_ingest.set_index("nombre_archivo")["tiempo_seg"])
        else:
            st.info("No ingestion logs yet.")

    with log2:
        if not df_search.empty:
            st.dataframe(df_search, width="stretch")
            if "latencia_ms" in df_search.columns and "tipo_busqueda" in df_search.columns:
                st.bar_chart(df_search.groupby("tipo_busqueda")["latencia_ms"].mean())
        else:
            st.info("No search logs yet.")

    with log3:
        if not df_gen.empty:
            st.dataframe(df_gen, width="stretch")
            if "tokens_out" in df_gen.columns and "tiempo_seg" in df_gen.columns:
                st.scatter_chart(df_gen, x="tokens_out", y="tiempo_seg", color="modelo")
        else:
            st.info("No generation logs yet.")

    # ── Budget Panel (NUEVO) ─────────────────────────────────────────────
    st.divider()
    st.subheader("💰 Estado del Presupuesto")
    try:
        from poc.budget_guard import get_budget_summary
        budget = get_budget_summary()

        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
        col_b1.metric("Gastado este mes", f"${budget['spent_usd']:.2f}")
        col_b2.metric("Budget mensual", f"${budget['budget_usd']:.2f}")
        col_b3.metric("% Usado", f"{budget['percentage']}%")
        col_b4.metric("Proyección mensual", f"${budget['projected_monthly']:.2f}")

        if budget["fallback_active"]:
            st.error(f"🔴 Modelo fallback activo: **{budget['active_model']}**")
        elif budget["status"] == "warning":
            st.warning(f"🟡 Budget al {budget['percentage']}% — modelo normal: **{budget['active_model']}**")
        else:
            st.success(f"🟢 Budget OK — modelo activo: **{budget['active_model']}**")
    except Exception as e:
        st.info(f"Budget tracking no disponible: {e}")


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


# ── TAB 7: NEO4J GRAPH EXPLORER ─────────────────────────────────────────────
_NEO4J_LABEL_COLORS = {
    "Entity": "#4FC3F7",
    "Episodic": "#FF8A65",
    "Community": "#AED581",
}
_NEO4J_DEFAULT_COLOR = "#B0BEC5"


def _neo4j_driver():
    from agent.config import settings as _cfg
    raw_uri = _cfg.NEO4J_URI
    # Force bolt:// scheme for standalone Neo4j — neo4j:// triggers cluster
    # routing discovery which fails with 'Unable to retrieve routing info'.
    uri = raw_uri.replace("neo4j://", "bolt://", 1).replace("neo4j+s://", "bolts://", 1)
    user = _cfg.NEO4J_USER
    pwd = _cfg.NEO4J_PASSWORD
    return GraphDatabase.driver(uri, auth=neo4j.basic_auth(user, pwd))


def _neo4j_query(driver, cypher, **params):
    with driver.session(database="neo4j") as s:
        return s.run(cypher, **params).data()


def _neo4j_single(driver, cypher):
    with driver.session(database="neo4j") as s:
        return s.run(cypher).single()


with tab_neo4j:
    st.header("Neo4j Graph Explorer")
    from agent.config import settings as _neo4j_cfg
    _effective_neo4j_uri = _neo4j_cfg.NEO4J_URI.replace("neo4j://", "bolt://", 1)
    st.caption(f"Connected to: `{_effective_neo4j_uri}`")

    try:
        _driver = _neo4j_driver()
        _driver.verify_connectivity()
    except Exception as exc:
        st.error(f"Cannot connect to Neo4j: {exc}")
        _driver = None

    if _driver:
        # ── Stats row ────────────────────────────────────────────────────
        n_nodes = _neo4j_single(_driver, "MATCH (n) RETURN count(n) AS c")["c"]
        n_rels = _neo4j_single(_driver, "MATCH ()-[r]->() RETURN count(r) AS c")["c"]
        lbl_data = _neo4j_query(_driver,
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS count ORDER BY count DESC")
        n_episodes = next((l["count"] for l in lbl_data if l["label"] == "Episodic"), 0)

        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Nodes", n_nodes)
        sc2.metric("Relationships", n_rels)
        sc3.metric("Episodes", n_episodes)
        sc4.metric("Entity Types", next((l["count"] for l in lbl_data if l["label"] == "Entity"), 0))

        # ── Sub-tabs ─────────────────────────────────────────────────────
        neo_tab_graph, neo_tab_episodes, neo_tab_details, neo_tab_query = st.tabs(
            ["Interactive Graph", "Episodes", "Details", "Cypher Query"]
        )

        # ── Interactive Graph ────────────────────────────────────────────
        with neo_tab_graph:
            gcol1, gcol2 = st.columns([1, 4])
            with gcol1:
                label_options = ["All"] + [l["label"] for l in lbl_data]
                lbl_filter = st.selectbox("Filter by label", label_options, key="neo_lbl")
                max_nodes = st.slider("Max nodes", 10, 500, 100, key="neo_max")
                physics_on = st.checkbox("Physics", True, key="neo_phys")

            with gcol2:
                if n_nodes == 0:
                    st.warning("No nodes in database.")
                else:
                    with st.spinner("Building graph..."):
                        # Fetch nodes
                        if lbl_filter != "All":
                            nodes_q = f"MATCH (n:{lbl_filter}) RETURN n, labels(n) AS labels LIMIT $lim"
                        else:
                            nodes_q = "MATCH (n) RETURN n, labels(n) AS labels LIMIT $lim"
                        raw_nodes = _neo4j_query(_driver, nodes_q, lim=max_nodes)

                        # Fetch rels
                        rels_q = (
                            "MATCH (a)-[r]->(b) "
                            "RETURN a.uuid AS a_uuid, a.name AS a_name, labels(a) AS a_labels, "
                            "       b.uuid AS b_uuid, b.name AS b_name, labels(b) AS b_labels, "
                            "       type(r) AS rel_type, properties(r) AS rel_props "
                            "LIMIT $lim"
                        )
                        raw_rels = _neo4j_query(_driver, rels_q, lim=max_nodes * 2)

                        # Build pyvis
                        net = Network(
                            height="650px", width="100%",
                            bgcolor="#1a1a2e", font_color="white",
                            directed=True, notebook=False,
                        )
                        if physics_on:
                            net.force_atlas_2based(
                                gravity=-50, central_gravity=0.01,
                                spring_length=150, spring_strength=0.08, damping=0.4,
                            )
                        else:
                            net.toggle_physics(False)

                        seen = set()

                        def _add_node(nid, name, labels_list):
                            if nid in seen:
                                return
                            seen.add(nid)
                            pl = labels_list[0] if labels_list else "Unknown"
                            color = _NEO4J_LABEL_COLORS.get(pl, _NEO4J_DEFAULT_COLOR)
                            sz = 25 if pl == "Episodic" else 18
                            net.add_node(
                                nid, label=str(name or "?")[:30],
                                title=f"<b>{name}</b><br>Label: {pl}",
                                color=color, size=sz,
                                font={"size": 12, "color": "white"},
                            )

                        # Add nodes from rels
                        for r in raw_rels:
                            a_id = r["a_uuid"] or r["a_name"] or "a?"
                            b_id = r["b_uuid"] or r["b_name"] or "b?"
                            _add_node(a_id, r["a_name"], r["a_labels"])
                            _add_node(b_id, r["b_name"], r["b_labels"])

                            props = r.get("rel_props") or {}
                            fact = str(props.get("fact", ""))[:200]
                            title = f"<b>{r['rel_type']}</b>"
                            if fact:
                                title += f"<br>{fact}"

                            net.add_edge(
                                a_id, b_id,
                                title=title,
                                label=r["rel_type"][:20],
                                color="#78909C", arrows="to",
                                font={"size": 8, "color": "#aaa"},
                            )

                        # Add standalone nodes
                        for rec in raw_nodes:
                            n = rec["n"]
                            nid = n.get("uuid") or n.get("name") or str(id(n))
                            _add_node(nid, n.get("name"), rec["labels"])

                        # Render
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".html", mode="w", encoding="utf-8"
                        ) as tmp:
                            net.save_graph(tmp.name)
                            with open(tmp.name, "r", encoding="utf-8") as fh:
                                html = fh.read()
                            st.components.v1.html(html, height=680, scrolling=False)

                        st.caption(f"Showing {len(seen)} nodes, {len(raw_rels)} relationships")

        # ── Episodes ─────────────────────────────────────────────────────
        with neo_tab_episodes:
            eps = _neo4j_query(_driver,
                "MATCH (e) WHERE 'Episodic' IN labels(e) "
                "RETURN e.name AS name, e.created_at AS created, "
                "e.group_id AS group_id, e.source_description AS source "
                "ORDER BY e.created_at")
            if eps:
                st.subheader(f"Ingested Episodes ({len(eps)})")
                for ep in eps:
                    with st.expander(ep.get("name") or "unnamed"):
                        st.json(ep)
            else:
                st.info("No episodic nodes found.")

        # ── Details ──────────────────────────────────────────────────────
        with neo_tab_details:
            dc1, dc2 = st.columns(2)
            with dc1:
                st.subheader("Node Labels")
                for l in lbl_data:
                    clr = _NEO4J_LABEL_COLORS.get(l["label"], _NEO4J_DEFAULT_COLOR)
                    st.markdown(
                        f'<span style="color:{clr};font-weight:600">{l["label"]}</span>: {l["count"]}',
                        unsafe_allow_html=True)
            with dc2:
                st.subheader("Relationship Types")
                rel_types = _neo4j_query(_driver,
                    "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC")
                for rt in rel_types:
                    st.markdown(f'`{rt["type"]}`: {rt["count"]}')

        # ── Custom Query ─────────────────────────────────────────────────
        with neo_tab_query:
            st.subheader("Run Cypher Query")
            default_cypher = "MATCH (n) RETURN n.name AS name, labels(n) AS labels LIMIT 25"
            cypher = st.text_area("Cypher", value=default_cypher, height=100, key="neo_cypher")
            if st.button("Execute", key="neo_exec"):
                try:
                    result = _neo4j_query(_driver, cypher)
                    if result:
                        st.dataframe(result, width="stretch")
                    else:
                        st.info("Query returned no results.")
                except Exception as qe:
                    st.error(f"Query error: {qe}")

        _driver.close()