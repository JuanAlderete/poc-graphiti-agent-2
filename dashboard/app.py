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

# FIXED: ensure standard event loop if uvloop is installed
try:
    import uvloop
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except ImportError:
    pass

# FIXED: patch the event loop so asyncio.run / await work inside Streamlit
nest_asyncio.apply()

from agent.config import settings
from agent.db_utils import DatabasePool, get_document_summary
from agent.tools import entity_search, hybrid_search, vector_search_with_diversity
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
from dashboard.i18n import t, LANGUAGES

# ---------------------------------------------------------------------------
# Language selection (must be first use of session_state)
# ---------------------------------------------------------------------------

if "lang" not in st.session_state:
    st.session_state["lang"] = "es"

lang = st.session_state["lang"]


# ---------------------------------------------------------------------------
# Helpers de configuración (.env)
# ---------------------------------------------------------------------------

ENV_FILE = ".env"

def _read_env_file() -> dict:
    """Lee el .env actual y retorna un dict con las variables."""
    env_vars = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip().strip('"').strip("'")
    return env_vars

def _write_env_file(env_vars: dict) -> None:
    """
    Escribe las variables en el .env.
    Lee el archivo existente para preservar comentarios y estructura,
    luego actualiza solo las variables que cambiaron.
    """
    # Leer contenido actual para preservar comentarios
    existing_lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    # Qué variables ya existen en el archivo
    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=")[0].strip()
            if key in env_vars:
                # Actualizar el valor
                new_lines.append(f"{key}={env_vars[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Agregar variables nuevas que no estaban en el archivo
    for key, value in env_vars.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

def _check_service(endpoint: str, payload: dict) -> dict:
    """Llama a un endpoint de config check de la API y retorna el resultado."""
    import requests
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    try:
        resp = requests.post(f"{api_base}{endpoint}", json=payload, timeout=15)
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}

def _restart_services():
    import subprocess
    import sys
    import os
    import time
    from agent.config import settings as _settings
    
    st.info(t("config.restarting", lang))
    time.sleep(1)
    
    # Intentar matar uvicorn (backend)
    try:
        if os.name == 'nt':
            subprocess.run("taskkill /F /IM uvicorn.exe /T", shell=True, capture_output=True)
        else:
            subprocess.run("pkill -f uvicorn", shell=True, capture_output=True)
    except:
        pass

    # Levantar uvicorn de nuevo
    port = str(getattr(_settings, "API_PORT", 8000))
    cmd_uvicorn = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", port, "--reload"]
    
    try:
        subprocess.Popen(cmd_uvicorn, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
    except Exception as e:
        st.error(f"Error levantando uvicorn: {e}")
        return

    # Reiniciar Streamlit
    try:
        os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", "dashboard/app.py"])
    except Exception as e:
        st.error(f"Error reiniciando dashboard: {e}")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title=t("app.page_title", lang),
    page_icon="🕸️",
    layout="wide",
)


def _(key: str, **kwargs) -> str:
    """Shortcut for t() using the current session language."""
    return t(key, lang=st.session_state["lang"], **kwargs)


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
    st.header(_("sidebar.config"))

    # Language selector
    st.subheader(_("sidebar.language"))
    selected_lang_label = st.radio(
        label="Language Selection",
        options=list(LANGUAGES.keys()),
        index=list(LANGUAGES.values()).index(st.session_state["lang"]),
        horizontal=True,
        label_visibility="collapsed",
    )
    if LANGUAGES[selected_lang_label] != st.session_state["lang"]:
        st.session_state["lang"] = LANGUAGES[selected_lang_label]
        st.rerun()

    lang = st.session_state["lang"]

    provider = os.getenv("LLM_PROVIDER", "openai").upper()
    st.info(t("sidebar.provider", lang, p=provider))
    st.divider()

    st.subheader(t("sidebar.actions", lang))
    if st.button(t("sidebar.clear_btn", lang), type="primary"):
        clear_all_logs()
        run_async(DatabasePool.clear_database())
        st.success(t("sidebar.clear_ok", lang))
        time.sleep(0.8)
        st.rerun()

    if st.button(t("sidebar.hydrate_btn", lang), help=t("sidebar.hydrate_help", lang)):
        from agent.config import settings as _cfg
        if not _cfg.ENABLE_GRAPH:
            st.warning("⚠️ El grafo está desactivado en la configuración (`ENABLE_GRAPH=false`). Activalo primero.")
        else:
            with st.spinner(t("sidebar.hydrate_spinner", lang)):
                try:
                    run_async(hydrate_graph(reset_flags=True))
                    st.success(t("sidebar.hydrate_ok", lang))
                except Exception as e:
                    st.error(t("sidebar.hydrate_err", lang, e=e))


# ---------------------------------------------------------------------------
# App title
# ---------------------------------------------------------------------------

st.title(t("app.title", lang))

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_ingest, tab_kb, tab_search, tab_gen, tab_analytics, tab_projections, tab_neo4j, tab_config = st.tabs([
    t("tab.ingestion", lang),
    t("tab.kb", lang),
    t("tab.search", lang),
    t("tab.gen", lang),
    t("tab.analytics", lang),
    t("tab.projections", lang),
    t("tab.neo4j", lang),
    "⚙️ Configuración",
])


# ── TAB 1: INGESTION ────────────────────────────────────────────────────────
with tab_ingest:
    st.header(t("ingest.header", lang))

    skip_graphiti_global = st.checkbox(
        t("ingest.skip_graphiti", lang),
        value=not getattr(settings, "ENABLE_GRAPH", False),
        help=t("ingest.skip_graphiti_help", lang),
    )

    # ── Modo 1: Subir archivos ───────────────────────────────────────────────
    st.subheader(t("ingest.upload_header", lang))
    uploaded_files = st.file_uploader(
        t("ingest.upload_label", lang),
        type=["txt", "md", "csv", "pdf"],
        accept_multiple_files=True,
        help=t("ingest.upload_help", lang),
    )

    if uploaded_files:
        st.info(t("ingest.upload_selected", lang, n=len(uploaded_files),
                   names=", ".join(f.name for f in uploaded_files)))

        if st.button(t("ingest.upload_btn", lang), type="primary"):
            save_dir = "documents_to_index"
            os.makedirs(save_dir, exist_ok=True)
            saved_paths = []

            with st.status(t("ingest.upload_processing", lang), expanded=True) as upload_status:
                st.write(t("ingest.upload_saving", lang))
                for uf in uploaded_files:
                    dest = os.path.join(save_dir, uf.name)
                    try:
                        raw = uf.read()
                        try:
                            text = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            text = raw.decode("latin-1", errors="replace")
                        with open(dest, "w", encoding="utf-8") as fh:
                            fh.write(text)
                        saved_paths.append(dest)
                        st.write(t("ingest.upload_saved_ok", lang, name=uf.name))
                    except Exception as e:
                        st.write(t("ingest.upload_saved_err", lang, name=uf.name, e=e))

                if not saved_paths:
                    upload_status.update(label=t("ingest.upload_no_valid", lang), state="error")
                else:
                    st.write(t("ingest.upload_indexing", lang, n=len(saved_paths)))
                    try:
                        from ingestion.ingest import ingest_files
                        run_async(ingest_files(saved_paths, skip_graphiti=skip_graphiti_global))
                        upload_status.update(
                            label=t("ingest.upload_done", lang, n=len(saved_paths)),
                            state="complete", expanded=False,
                        )
                        st.success(t("ingest.upload_success", lang))
                    except Exception as exc:
                        upload_status.update(label=t("ingest.upload_no_valid", lang), state="error")
                        st.error(t("ingest.upload_ingest_err", lang, e=exc))

    st.divider()

    # ── Modo 2: Directorio existente ─────────────────────────────────────────
    st.subheader(t("ingest.dir_header", lang))
    col1, col2 = st.columns([3, 1])
    with col1:
        docs_dir = st.text_input(t("ingest.dir_label", lang), value="documents_to_index")
    with col2:
        st.write("")
        st.write("")

    if st.button(t("ingest.dir_btn", lang)):
        if not os.path.exists(docs_dir):
            st.error(t("ingest.dir_not_found", lang, d=docs_dir))
        else:
            with st.status(t("ingest.dir_spinner", lang), expanded=True) as status:
                st.write(t("ingest.dir_init", lang))
                try:
                    run_async(run_ingestion(docs_dir, skip_graphiti=skip_graphiti_global))
                    status.update(label=t("ingest.dir_done", lang), state="complete", expanded=False)
                    st.success(t("ingest.dir_success", lang, d=docs_dir))
                except Exception as exc:
                    status.update(label=t("ingest.dir_failed", lang), state="error")
                    st.error(t("ingest.dir_err", lang, e=exc))


# ── TAB 2: KNOWLEDGE BASE ───────────────────────────────────────────────────
with tab_kb:
    st.header(t("kb.header", lang))
    if st.button(t("kb.refresh", lang), key="refresh_kb"):
        st.rerun()

    try:
        docs = run_async(get_document_summary())
        if not docs:
            st.info(t("kb.no_docs", lang))
        else:
            df_docs = pd.DataFrame(docs)
            # Ensure all object columns (like UUIDs) are strings for Arrow serialization
            for col in df_docs.columns:
                if df_docs[col].dtype == "object":
                    df_docs[col] = df_docs[col].astype(str)
            total_docs = len(df_docs)
            total_chunks = df_docs["chunk_count"].sum() if "chunk_count" in df_docs.columns else 0

            c1, c2 = st.columns(2)
            c1.metric(t("kb.total_docs", lang), total_docs)
            c2.metric(t("kb.total_chunks", lang), total_chunks)

            st.divider()

            filter_txt = st.text_input(t("kb.filter", lang), "", key="kb_filter")
            if filter_txt:
                df_docs = df_docs[
                    df_docs["title"].str.contains(filter_txt, case=False, na=False) |
                    df_docs["source"].str.contains(filter_txt, case=False, na=False)
                ]

            st.dataframe(
                df_docs,
                column_config={
                    "title": st.column_config.TextColumn(t("kb.col_title", lang)),
                    "source": st.column_config.TextColumn(t("kb.col_path", lang)),
                    "chunk_count": st.column_config.NumberColumn(t("kb.col_chunks", lang)),
                    "total_tokens": st.column_config.NumberColumn("Tokens"),
                    "graph_ingested": st.column_config.CheckboxColumn("En Grafo"),
                    "has_graphiti_node": st.column_config.CheckboxColumn("ID Graphiti"),
                    "created_at": st.column_config.DatetimeColumn(t("kb.col_ingested", lang), format="D MMM YYYY, h:mm a"),
                },
                width="stretch",
                hide_index=True,
            )
    except Exception as e:
        st.error(t("kb.error", lang, e=e))


# ── TAB 3: SEARCH ───────────────────────────────────────────────────────────
with tab_search:
    st.header(t("search.header", lang))

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_area(t("search.query_label", lang), t("search.query_default", lang))
    with col2:
        _search_types = t("search.types", lang)
        search_type = st.radio(t("search.type_label", lang), _search_types, index=2)

    if st.button(t("search.btn", lang)):
        with st.spinner(t("search.spinner", lang, t=search_type)):
            try:
                # Map display label back to function (works for both languages)
                _type_lower = search_type.lower()
                if _type_lower in ("vector",):
                    results = run_async(vector_search_with_diversity(None, query_embedding=run_async(get_content_generator()._get_embedding(query))))
                elif _type_lower in ("graph", "grafo"):
                    results = run_async(entity_search([query]))
                else:
                    results = run_async(hybrid_search(query, query_embedding=run_async(get_content_generator()._get_embedding(query))))

                st.subheader(t("search.results", lang, n=len(results)))

                debug_mode = st.checkbox(t("search.debug", lang), value=False)

                for i, r in enumerate(results, 1):
                    with st.expander(f"#{i} — {t('search.score', lang)} {r.score:.3f} [{r.document_title}]"):
                        st.markdown(r.content)
                        if debug_mode:
                            st.caption(t("search.raw_data", lang))
                            st.json(r.__dict__)
                        elif r.metadata:
                            st.caption(t("search.metadata", lang))
                            st.json(r.metadata)
            except Exception as exc:
                st.error(t("search.error", lang, e=exc))


# ── TAB 4: GENERATION ───────────────────────────────────────────────────────
with tab_gen:
    st.header(t("gen.header", lang))

    _templates = t("gen.templates", lang)
    template_type = st.selectbox(t("gen.template_label", lang), _templates)

    prompt = system_prompt = ""
    formato = "text"
    topic = ""

    if template_type in (_templates[0],):  # Cold Email / Email Frío
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input(t("gen.topic", lang), t("gen.email_topic_default", lang))
            objective = st.text_input(t("gen.objective", lang), t("gen.email_objective_default", lang))
        with col2:
            context = st.text_area(t("gen.context", lang), t("gen.email_context_default", lang))
        system_prompt = email.SYSTEM_PROMPT
        prompt = email.PROMPT_TEMPLATE.format(topic=topic, context=context, objective=objective)
        formato = "email"

    elif template_type in (_templates[1],):  # Startup Story / Historia de Startup
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input(t("gen.topic", lang), t("gen.historia_topic_default", lang))
            tone = st.text_input(t("gen.tone", lang), t("gen.historia_tone_default", lang))
        with col2:
            context = st.text_area(t("gen.context", lang), t("gen.historia_context_default", lang), height=100)
        system_prompt = historia.SYSTEM_PROMPT
        prompt = historia.PROMPT_TEMPLATE.format(topic=topic, context=context, tone=tone)
        formato = "historia"

    elif template_type in (_templates[2],):  # Instagram Reel / Reel de Instagram
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input(t("gen.topic", lang), t("gen.reel_topic_default", lang))
            cta = st.text_input(t("gen.cta", lang), t("gen.reel_cta_default", lang))
        with col2:
            context = st.text_input(t("gen.context", lang), t("gen.reel_context_default", lang))
        system_prompt = reel_cta.SYSTEM_PROMPT
        prompt = reel_cta.PROMPT_TEMPLATE.format(topic=topic, context=context, cta=cta)
        formato = "reel_cta"

    elif template_type in (_templates[3],):  # Custom / Personalizado
        topic = st.text_input(t("gen.topic", lang), t("gen.custom_topic_default", lang))
        system_prompt = st.text_area(t("gen.system_prompt", lang), t("gen.custom_system_default", lang))
        prompt = st.text_area(t("gen.prompt", lang), t("gen.custom_prompt_default", lang), height=150)
        formato = "custom"

    if st.button(t("gen.btn", lang)):
        with st.spinner(t("gen.spinner", lang)):
            try:
                generator = get_content_generator()
                content = run_async(
                    generator.generate(prompt, system_prompt, formato=formato, tema=topic)
                )
                st.subheader(t("gen.result_header", lang))
                st.markdown(content)
                st.divider()
                st.caption(t("gen.generated_with", lang, p=provider))
            except Exception as exc:
                st.error(t("gen.error", lang, e=exc))

    # ── Sección: Agentes Estructurados ────────────────────────────────────────
    st.divider()
    st.subheader(t("gen.agent_header", lang))
    st.caption(t("gen.agent_caption", lang))

    col_fmt, col_topic = st.columns(2)
    with col_fmt:
        new_formato = st.selectbox(
            t("gen.agent_format", lang),
            ["reel_cta", "historia", "email", "reel_lead_magnet", "ads"],
            key="new_gen_formato",
        )
    with col_topic:
        new_topic = st.text_input(t("gen.agent_topic", lang), t("gen.agent_topic_default", lang), key="new_gen_topic")

    new_context = st.text_area(t("gen.agent_context", lang), "", height=100, key="new_gen_context")

    extra_params = {}
    if new_formato == "reel_cta":
        extra_params["cta"] = st.text_input(t("gen.cta", lang), t("gen.reel_cta_agent_default", lang), key="reel_cta_cta")
    elif new_formato == "historia":
        extra_params["tone"] = st.text_input(t("gen.tone", lang), t("gen.historia_tone_agent_default", lang), key="historia_tone")
        _historia_opts = t("gen.historia_tipo_options", lang)
        extra_params["tipo"] = st.selectbox(t("gen.historia_tipo_label", lang), _historia_opts, key="historia_tipo")
    elif new_formato == "email":
        extra_params["objective"] = st.text_input(t("gen.objective", lang), t("gen.email_objective_agent_default", lang), key="email_obj")
    elif new_formato == "reel_lead_magnet":
        extra_params["lead_magnet"] = st.text_input(t("gen.lead_magnet_label", lang), t("gen.lead_magnet_default", lang), key="rlm_lm")
    elif new_formato == "ads":
        _ads_opts = t("gen.ads_tipo_options", lang)
        extra_params["tipo"] = st.selectbox(t("gen.ads_tipo_label", lang), _ads_opts, key="ads_tipo")

    if st.button(t("gen.agent_btn", lang)):
        with st.spinner(t("gen.agent_spinner", lang, f=new_formato)):
            try:
                from services.generation_service import GenerationService
                from poc.budget_guard import get_budget_summary

                if not new_context:
                    # Usamos hybrid_search con la extracción de embedding automática
                    gen = get_content_generator()
                    q_emb = run_async(gen._get_embedding(new_topic))
                    results = run_async(hybrid_search(new_topic, query_embedding=q_emb, limit=3))
                    context_for_gen = "\n\n---\n\n".join(r.content for r in results) if results else t("gen.no_context_fallback", lang)
                else:
                    context_for_gen = new_context

                service = GenerationService()
                output = run_async(service.generate(new_formato, topic=new_topic, context=context_for_gen, **extra_params))

                budget = get_budget_summary()
                if budget["status"] == "critical":
                    st.warning(t("gen.agent_budget_critical", lang, pct=budget["percentage"], m=budget["active_model"]))
                elif budget["status"] == "warning":
                    st.info(t("gen.agent_budget_warn", lang,
                               pct=budget["percentage"], spent=budget["spent_usd"], budget=budget["budget_usd"]))

                qa_result = "PASSED" if output.qa_passed else "FAILED"
                st.success(t("gen.agent_qa", lang, r=qa_result, c=output.cost_usd))

                if not output.qa_passed:
                    st.warning(t("gen.agent_qa_notes", lang, n=output.qa_notes))

                st.json(output.data)

            except Exception as exc:
                st.error(t("gen.agent_error", lang, e=exc))


# ── TAB 5: ANALYTICS ────────────────────────────────────────────────────────
with tab_analytics:
    st.header(t("analytics.header", lang))
    if st.button(t("analytics.refresh", lang)):
        st.rerun()

    df_ingest = load_log("ingesta_log.csv")
    df_search = load_log("busqueda_log.csv")
    df_gen = load_log("generacion_log.csv")

    total_cost = 0.0
    if not df_ingest.empty and "costo_total_usd" in df_ingest.columns:
        total_cost += df_ingest["costo_total_usd"].sum()
    if not df_gen.empty and "costo_usd" in df_gen.columns:
        total_cost += df_gen["costo_usd"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t("analytics.total_cost", lang), f"${total_cost:.4f}")
    c2.metric(t("analytics.files_ingested", lang), len(df_ingest) if not df_ingest.empty else 0)
    c3.metric(t("analytics.searches", lang), len(df_search) if not df_search.empty else 0)
    c4.metric(t("analytics.generated", lang), len(df_gen) if not df_gen.empty else 0)
    st.divider()

    st.subheader(t("analytics.cost_evolution", lang))
    cost_data = []
    _label_time = t("analytics.axis_time", lang)
    _label_cost = t("analytics.axis_cost", lang)
    _label_type = t("analytics.axis_type", lang)

    if not df_ingest.empty and "timestamp" in df_ingest.columns:
        for _, r in df_ingest.iterrows():
            cost_data.append({
                _label_time: r["timestamp"],
                _label_cost: r.get("costo_total_usd", 0),
                _label_type: t("tab.ingestion", lang)
            })
    if not df_search.empty and "timestamp" in df_search.columns:
        for _, r in df_search.iterrows():
            cost_data.append({
                _label_time: r["timestamp"],
                _label_cost: r.get("costo_total_usd", 0),
                _label_type: t("tab.search", lang)
            })
    if not df_gen.empty and "timestamp" in df_gen.columns:
        for _, r in df_gen.iterrows():
            cost_data.append({
                _label_time: r["timestamp"],
                _label_cost: r.get("costo_usd", 0),
                _label_type: t("tab.gen", lang)
            })

    if cost_data:
        df_cost = pd.DataFrame(cost_data)
        df_cost[_label_time] = pd.to_datetime(df_cost[_label_time], unit="s")
        st.scatter_chart(df_cost, x=_label_time, y=_label_cost, color=_label_type)
    else:
        st.info(t("analytics.no_cost_data", lang))

    st.divider()

    log1, log2, log3 = st.tabs([
        t("analytics.log_ingestion", lang),
        t("analytics.log_search", lang),
        t("analytics.log_gen", lang),
    ])

    with log1:
        if not df_ingest.empty:
            st.dataframe(df_ingest, width="stretch")
            if "tiempo_seg" in df_ingest.columns and "nombre_archivo" in df_ingest.columns:
                st.bar_chart(df_ingest.set_index("nombre_archivo")["tiempo_seg"])
        else:
            st.info(t("analytics.no_ingest_logs", lang))

    with log2:
        if not df_search.empty:
            st.dataframe(df_search, width="stretch")
            if "latencia_ms" in df_search.columns and "tipo_busqueda" in df_search.columns:
                st.bar_chart(df_search.groupby("tipo_busqueda")["latencia_ms"].mean())
        else:
            st.info(t("analytics.no_search_logs", lang))

    with log3:
        if not df_gen.empty:
            st.dataframe(df_gen, width="stretch")
            if "tokens_out" in df_gen.columns and "tiempo_seg" in df_gen.columns:
                st.scatter_chart(df_gen, x="tokens_out", y="tiempo_seg", color="modelo")
        else:
            st.info(t("analytics.no_gen_logs", lang))

    # ── Budget Panel ─────────────────────────────────────────────────────────
    st.divider()
    st.subheader(t("analytics.budget_header", lang))
    try:
        from poc.budget_guard import get_budget_summary
        budget = get_budget_summary()

        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
        col_b1.metric(t("analytics.budget_spent", lang), f"${budget['spent_usd']:.2f}")
        col_b2.metric(t("analytics.budget_total", lang), f"${budget['budget_usd']:.2f}")
        col_b3.metric(t("analytics.budget_pct", lang), f"{budget['percentage']}%")
        col_b4.metric(t("analytics.budget_projection", lang), f"${budget['projected_monthly']:.2f}")

        if budget["fallback_active"]:
            st.error(t("analytics.budget_fallback", lang, m=budget["active_model"]))
        elif budget["status"] == "warning":
            st.warning(t("analytics.budget_warn", lang, pct=budget["percentage"], m=budget["active_model"]))
        else:
            st.success(t("analytics.budget_ok", lang, m=budget["active_model"]))
    except Exception as e:
        st.info(t("analytics.budget_unavail", lang, e=e))


# ── TAB 6: PROYECCIONES ─────────────────────────────────────────────────────
with tab_projections:
    st.header(t("proj.header", lang))
    st.caption(t("proj.caption", lang))

    col1, col2, col3 = st.columns(3)
    with col1:
        docs_per_month = st.number_input(t("proj.docs_month", lang), min_value=1, value=250, step=10)
    with col2:
        queries_per_month = st.number_input(t("proj.queries_month", lang), min_value=0, value=5000, step=100)
    with col3:
        pieces_per_month = st.number_input(t("proj.pieces_month", lang), min_value=0, value=200, step=10)

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
    c1.metric(t("proj.ingest_month", lang), f"${monthly_ingest:.2f}")
    c2.metric(t("proj.search_month", lang), f"${monthly_search:.2f}")
    c3.metric(t("proj.gen_month", lang), f"${monthly_gen:.2f}")
    c4.metric(t("proj.total_month", lang), f"${monthly_total:.2f}")

    st.metric(t("proj.annual", lang), f"${annual_total:.2f}")

    st.divider()
    if monthly_total < 100:
        st.success(t("proj.go", lang))
    elif monthly_total < 200:
        st.warning(t("proj.optimize", lang))
    else:
        st.error(t("proj.stop", lang))

    _source = t("proj.source_logs", lang) if not df_ingest.empty else t("proj.source_default", lang)
    with st.expander(t("proj.unit_costs", lang)):
        st.write({
            "avg_ingest_cost_usd": round(avg_ingest_cost, 6),
            "avg_search_cost_usd": round(avg_search_cost, 6),
            "avg_generation_cost_usd": round(avg_gen_cost, 6),
            "source": _source,
        })


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
    # Force bolt:// scheme — neo4j:// triggers cluster routing which fails on standalone
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
    st.header(t("neo4j.header", lang))

    if not settings.ENABLE_GRAPH:
        st.info(t("neo4j.disabled_info", lang))
    else:
        _effective_neo4j_uri = settings.NEO4J_URI.replace("neo4j://", "bolt://", 1)
        st.caption(t("neo4j.connected", lang, uri=_effective_neo4j_uri))

        _driver = None
        try:
            _driver = _neo4j_driver()
            _driver.verify_connectivity()
        except Exception as exc:
            st.error(t("neo4j.error", lang, e=exc))
            _driver = None

        if _driver:
            n_nodes = _neo4j_single(_driver, "MATCH (n) RETURN count(n) AS c")["c"]
            n_rels = _neo4j_single(_driver, "MATCH ()-[r]->() RETURN count(r) AS c")["c"]
            lbl_data = _neo4j_query(_driver,
                "MATCH (n) UNWIND labels(n) AS label "
                "RETURN label, count(*) AS count ORDER BY count DESC")
            n_episodes = next((l["count"] for l in lbl_data if l["label"] == "Episodic"), 0)

            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric(t("neo4j.nodes", lang), n_nodes)
            sc2.metric(t("neo4j.rels", lang), n_rels)
            sc3.metric(t("neo4j.episodes", lang), n_episodes)
            sc4.metric(t("neo4j.entity_types", lang), next((l["count"] for l in lbl_data if l["label"] == "Entity"), 0))

            neo_tab_graph, neo_tab_episodes, neo_tab_details, neo_tab_query = st.tabs([
                t("neo4j.subtab_graph", lang),
                t("neo4j.subtab_episodes", lang),
                t("neo4j.subtab_details", lang),
                t("neo4j.subtab_query", lang),
            ])

            with neo_tab_graph:
                gcol1, gcol2 = st.columns([1, 4])
                with gcol1:
                    _all_label = t("neo4j.filter_all", lang)
                    label_options = [_all_label] + [l["label"] for l in lbl_data]
                    lbl_filter = st.selectbox(t("neo4j.filter_label", lang), label_options, key="neo_lbl")
                    max_nodes = st.slider(t("neo4j.max_nodes", lang), 10, 500, 100, key="neo_max")
                    physics_on = st.checkbox(t("neo4j.physics", lang), True, key="neo_phys")

                with gcol2:
                    if n_nodes == 0:
                        st.warning(t("neo4j.no_nodes", lang))
                    else:
                        with st.spinner(t("neo4j.building", lang)):
                            if lbl_filter != _all_label:
                                nodes_q = f"MATCH (n:{lbl_filter}) RETURN n, labels(n) AS labels LIMIT $lim"
                            else:
                                nodes_q = "MATCH (n) RETURN n, labels(n) AS labels LIMIT $lim"
                            raw_nodes = _neo4j_query(_driver, nodes_q, lim=max_nodes)

                            rels_q = (
                                "MATCH (a)-[r]->(b) "
                                "RETURN a.uuid AS a_uuid, a.name AS a_name, labels(a) AS a_labels, "
                                "       b.uuid AS b_uuid, b.name AS b_name, labels(b) AS b_labels, "
                                "       type(r) AS rel_type, properties(r) AS rel_props "
                                "LIMIT $lim"
                            )
                            raw_rels = _neo4j_query(_driver, rels_q, lim=max_nodes * 2)

                            net = Network(height="650px", width="100%", bgcolor="#1a1a2e", font_color="white", directed=True, notebook=False)
                            if physics_on:
                                net.force_atlas_2based(gravity=-50, central_gravity=0.01, spring_length=150, spring_strength=0.08, damping=0.4)
                            else:
                                net.toggle_physics(False)

                            seen = set()

                            def _add_node(nid, name, labels_list):
                                if nid in seen:
                                    return
                                seen.add(nid)
                                pl = labels_list[0] if labels_list else t("neo4j.unknown", lang)
                                color = _NEO4J_LABEL_COLORS.get(pl, _NEO4J_DEFAULT_COLOR)
                                sz = 25 if pl == "Episodic" else 18
                                net.add_node(nid, label=str(name or "?")[:30], title=f"<b>{name}</b><br>{t('neo4j.label', lang)}: {pl}", color=color, size=sz, font={"size": 12, "color": "white"})

                            for r in raw_rels:
                                a_id = r["a_uuid"] or r["a_name"] or "a?"
                                b_id = r["b_uuid"] or r["b_name"] or "b?"
                                _add_node(a_id, r["a_name"], r["a_labels"])
                                _add_node(b_id, r["b_name"], r["b_labels"])
                                props = r.get("rel_props") or {}
                                fact = str(props.get("fact", ""))[:200]
                                title = f"<b>{r['rel_type']}</b>"
                                if fact: title += f"<br>{fact}"
                                net.add_edge(a_id, b_id, title=title, label=r["rel_type"][:20], color="#78909C", arrows="to", font={"size": 8, "color": "#aaa"})

                            for rec in raw_nodes:
                                n = rec["n"]
                                nid = n.get("uuid") or n.get("name") or str(id(n))
                                _add_node(nid, n.get("name"), rec["labels"])

                            with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as tmp:
                                net.save_graph(tmp.name)
                                with open(tmp.name, "r", encoding="utf-8") as fh:
                                    html = fh.read()
                                st.components.v1.html(html, height=680, scrolling=False)

                            st.caption(t("neo4j.showing", lang, n=len(seen), r=len(raw_rels)))

            with neo_tab_episodes:
                eps = _neo4j_query(_driver, "MATCH (e) WHERE 'Episodic' IN labels(e) RETURN e.name AS name, e.created_at AS created, e.group_id AS group_id, e.source_description AS source ORDER BY e.created_at")
                if eps:
                    st.subheader(t("neo4j.episodes_header", lang, n=len(eps)))
                    for ep in eps:
                        with st.expander(ep.get("name") or "unnamed"):
                            st.json(ep)
                else:
                    st.info(t("neo4j.no_episodes", lang))

            with neo_tab_details:
                dc1, dc2 = st.columns(2)
                with dc1:
                    st.subheader(t("neo4j.node_labels", lang))
                    for l in lbl_data:
                        clr = _NEO4J_LABEL_COLORS.get(l["label"], _NEO4J_DEFAULT_COLOR)
                        st.markdown(f'<span style="color:{clr};font-weight:600">{l["label"]}</span>: {l["count"]}', unsafe_allow_html=True)
                with dc2:
                    st.subheader(t("neo4j.rel_types", lang))
                    rel_types = _neo4j_query(_driver, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC")
                    for rt in rel_types:
                        st.markdown(f'`{rt["type"]}`: {rt["count"]}')

            with neo_tab_query:
                st.subheader(t("neo4j.cypher_header", lang))
                cypher = st.text_area(t("neo4j.cypher_label", lang), value="MATCH (n) RETURN n.name AS name, labels(n) AS labels LIMIT 25", height=100, key="neo_cypher")
                if st.button(t("neo4j.cypher_btn", lang), key="neo_exec"):
                    try:
                        result = _neo4j_query(_driver, cypher)
                        if result:
                            df_res = pd.DataFrame(result)
                            for col in df_res.columns:
                                if df_res[col].dtype == "object": df_res[col] = df_res[col].astype(str)
                            st.dataframe(df_res, width="stretch")
                        else:
                            st.info(t("neo4j.cypher_no_results", lang))
                    except Exception as qe:
                        st.error(t("neo4j.cypher_error", lang, e=qe))

            _driver.close()

# ── TAB CONFIGURACIÓN ────────────────────────────────────────────────────────
with tab_config:
    st.header("⚙️ Configuración del Sistema")
    st.caption("Configurá todos los parámetros del sistema. Los cambios se guardan en el archivo `.env`.")

    # Leer valores actuales del .env
    current_env = _read_env_file()

    # Función helper para mostrar el resultado de un chequeo
    def _show_check_result(result: dict):
        if result.get("status") == "ok":
            st.success(f"✅ {result.get('message', 'Conexión exitosa')}")
        else:
            st.error(f"❌ {result.get('message', 'Error desconocido')}")

    # ── Sección 1: Proveedor LLM ──────────────────────────────────────────
    st.subheader("🤖 Proveedor LLM")
    st.caption("El proveedor controla qué API se usa para generar contenido Y para crear embeddings.")

    col_prov, col_info = st.columns([2, 3])
    with col_prov:
        provider_options = ["openai", "ollama", "gemini"]
        current_provider = current_env.get("LLM_PROVIDER", "openai")
        selected_provider = st.selectbox(
            "Proveedor activo",
            options=provider_options,
            index=provider_options.index(current_provider) if current_provider in provider_options else 0,
            key="cfg_provider",
        )
    with col_info:
        provider_info = {
            "openai": "🌐 **OpenAI API** — Mejor calidad. Requiere API key. Tiene costo por token.",
            "ollama": "🏠 **Ollama local** — Sin costo. Datos no salen del servidor. Requiere GPU o paciencia.",
            "gemini": "💎 **Google Gemini** — Alternativa económica. Requiere API key de Google.",
        }
        st.info(provider_info.get(selected_provider, ""))

    st.divider()

    # ── Sección 2: Credenciales según proveedor ───────────────────────────
    st.subheader("🔑 API Keys y Credenciales")

    cfg_to_save = {}

    if selected_provider == "openai":
        openai_key = st.text_input(
            "OpenAI API Key",
            value=current_env.get("OPENAI_API_KEY", ""),
            type="password",
            help="Empeza con 'sk-'. Obtenerla en https://platform.openai.com/api-keys",
            key="cfg_openai_key",
        )
        openai_base_url = st.text_input(
            "Base URL (dejar vacío para OpenAI oficial)",
            value=current_env.get("OPENAI_BASE_URL", ""),
            placeholder="https://api.openai.com/v1",
            help="Solo cambiar si usás un proxy o Azure OpenAI",
            key="cfg_openai_url",
        )
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            default_model = st.text_input(
                "Modelo principal",
                value=current_env.get("DEFAULT_MODEL", "gpt-4.1-mini"),
                placeholder="gpt-4.1-mini",
                key="cfg_default_model",
            )
        with col_m2:
            fallback_model = st.text_input(
                "Modelo fallback (cuando budget > 90%)",
                value=current_env.get("FALLBACK_MODEL", "gpt-4.1-mini"),
                placeholder="gpt-4.1-mini",
                key="cfg_fallback_model",
            )

        col_check_llm, _ = st.columns([1, 3])
        with col_check_llm:
            if st.button("🔍 Verificar conexión OpenAI", key="check_openai"):
                with st.spinner("Verificando API key..."):
                    r = _check_service("/config/check/llm", {
                        "provider": "openai",
                        "api_key": openai_key,
                        "base_url": openai_base_url or None,
                    })
                _show_check_result(r)

        cfg_to_save.update({
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": openai_key,
            "OPENAI_BASE_URL": openai_base_url,
            "DEFAULT_MODEL": default_model,
            "FALLBACK_MODEL": fallback_model,
        })

    elif selected_provider == "ollama":
        ollama_url = st.text_input(
            "URL de Ollama",
            value=current_env.get("OPENAI_BASE_URL", "http://localhost:11434/v1"),
            placeholder="http://localhost:11434/v1",
            help="URL base de Ollama. En Docker: http://ollama:11434/v1",
            key="cfg_ollama_url",
        )
        col_om1, col_om2 = st.columns(2)
        with col_om1:
            ollama_model = st.text_input(
                "Modelo de generación",
                value=current_env.get("DEFAULT_MODEL", "llama3.1:8b"),
                placeholder="llama3.1:8b",
                help="Debe estar descargado: ollama pull llama3.1:8b",
                key="cfg_ollama_model",
            )
        with col_om2:
            ollama_embed = st.text_input(
                "Modelo de embeddings",
                value=current_env.get("EMBEDDING_MODEL", "nomic-embed-text"),
                placeholder="nomic-embed-text",
                help="Debe estar descargado: ollama pull nomic-embed-text",
                key="cfg_ollama_embed",
            )
        st.caption("⚠️ Si cambiás el modelo de embeddings, ejecutá `bash scripts/reset_db.sh` para reiniciar la DB.")

        col_check_ollama, _ = st.columns([1, 3])
        with col_check_ollama:
            if st.button("🔍 Verificar conexión Ollama", key="check_ollama"):
                with st.spinner("Verificando Ollama..."):
                    r = _check_service("/config/check/llm", {
                        "provider": "ollama",
                        "base_url": ollama_url,
                    })
                _show_check_result(r)

        cfg_to_save.update({
            "LLM_PROVIDER": "ollama",
            "OPENAI_API_KEY": "ollama",
            "OPENAI_BASE_URL": ollama_url,
            "DEFAULT_MODEL": ollama_model,
            "EMBEDDING_MODEL": ollama_embed,
        })

    elif selected_provider == "gemini":
        gemini_key = st.text_input(
            "Gemini API Key",
            value=current_env.get("GEMINI_API_KEY", ""),
            type="password",
            help="Obtenerla en https://aistudio.google.com/app/apikey",
            key="cfg_gemini_key",
        )

        col_check_gemini, _ = st.columns([1, 3])
        with col_check_gemini:
            if st.button("🔍 Verificar conexión Gemini", key="check_gemini"):
                with st.spinner("Verificando Gemini..."):
                    r = _check_service("/config/check/llm", {
                        "provider": "gemini",
                        "gemini_api_key": gemini_key,
                    })
                _show_check_result(r)

        cfg_to_save.update({
            "LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": gemini_key,
        })

    st.divider()

    # ── Sección 3: PostgreSQL ─────────────────────────────────────────────
    st.subheader("🐘 Base de Datos (PostgreSQL)")

    col_pg1, col_pg2 = st.columns(2)
    with col_pg1:
        pg_host = st.text_input("Host", value=current_env.get("POSTGRES_HOST", "localhost"), key="cfg_pg_host")
        pg_db   = st.text_input("Database", value=current_env.get("POSTGRES_DB", "marketingmaker"), key="cfg_pg_db")
        pg_user = st.text_input("Usuario", value=current_env.get("POSTGRES_USER", "marketingmaker"), key="cfg_pg_user")
    with col_pg2:
        pg_port = st.number_input("Puerto", value=int(current_env.get("POSTGRES_PORT", "5432")), min_value=1, max_value=65535, key="cfg_pg_port")
        pg_pass = st.text_input("Password", value=current_env.get("POSTGRES_PASSWORD", ""), type="password", key="cfg_pg_pass")

    col_check_pg, _ = st.columns([1, 3])
    with col_check_pg:
        if st.button("🔍 Verificar conexión Postgres", key="check_pg"):
            with st.spinner("Verificando Postgres..."):
                r = _check_service("/config/check/postgres", {
                    "host": pg_host, "port": pg_port,
                    "database": pg_db, "user": pg_user, "password": pg_pass,
                })
            _show_check_result(r)

    cfg_to_save.update({
        "POSTGRES_HOST": pg_host,
        "POSTGRES_PORT": str(pg_port),
        "POSTGRES_DB": pg_db,
        "POSTGRES_USER": pg_user,
        "POSTGRES_PASSWORD": pg_pass,
    })

    st.divider()

    # ── Sección 4: Notion ─────────────────────────────────────────────────
    st.subheader("📋 Notion")
    st.caption("Configurá el token y los IDs de cada base de datos. Los IDs están en la URL de cada DB en Notion.")

    notion_token = st.text_input(
        "Token de integración Notion",
        value=current_env.get("NOTION_TOKEN", ""),
        type="password",
        help="Obtenerlo en https://www.notion.so/my-integrations",
        key="cfg_notion_token",
    )

    col_check_notion, _ = st.columns([1, 3])
    with col_check_notion:
        if st.button("🔍 Verificar token Notion", key="check_notion"):
            with st.spinner("Verificando Notion..."):
                r = _check_service("/config/check/notion", {"token": notion_token})
            _show_check_result(r)

    st.caption("**IDs de bases de datos** — Copiar de la URL de cada DB en Notion (el UUID al final)")

    notion_dbs = {}
    db_labels = {
        "NOTION_RULES_DB":    "Weekly Rules DB",
        "NOTION_REELS_DB":    "Reels DB (output)",
        "NOTION_HISTORIA_DB": "Historias DB (output)",
        "NOTION_EMAIL_DB":    "Emails DB (output)",
        "NOTION_ADS_DB":      "Ads DB (output)",
        "NOTION_RUNS_DB":     "Weekly Runs DB (log)",
    }

    cols_notion = st.columns(2)
    for idx, (env_key, label) in enumerate(db_labels.items()):
        with cols_notion[idx % 2]:
            db_value = st.text_input(
                label,
                value=current_env.get(env_key, ""),
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                key=f"cfg_{env_key}",
            )
            notion_dbs[env_key] = db_value

            # Botón individual de verificación para cada DB
            if db_value and notion_token:
                if st.button(f"Verificar acceso", key=f"check_db_{env_key}"):
                    with st.spinner(f"Verificando {label}..."):
                        r = _check_service("/config/check/notion", {
                            "token": notion_token,
                            "database_id": db_value,
                        })
                    _show_check_result(r)

    cfg_to_save["NOTION_TOKEN"] = notion_token
    cfg_to_save.update(notion_dbs)

    st.divider()

    # ── Sección 5: Telegram ───────────────────────────────────────────────
    st.subheader("💬 Telegram (notificaciones)")
    st.caption("Opcional. Si no configurás esto, el sistema funciona pero no enviará alertas.")

    col_tg1, col_tg2 = st.columns(2)
    with col_tg1:
        tg_token = st.text_input(
            "Bot Token",
            value=current_env.get("TELEGRAM_BOT_TOKEN", ""),
            type="password",
            help="Obtenerlo hablando con @BotFather en Telegram",
            key="cfg_tg_token",
        )
    with col_tg2:
        tg_chat = st.text_input(
            "Chat ID",
            value=current_env.get("TELEGRAM_CHAT_ID", ""),
            placeholder="-100xxxxxxxxxx",
            help="ID del grupo o canal. Usar @userinfobot para obtenerlo.",
            key="cfg_tg_chat",
        )

    col_check_tg, _ = st.columns([1, 3])
    with col_check_tg:
        if st.button("🔍 Verificar y enviar mensaje de prueba", key="check_tg"):
            if not tg_token or not tg_chat:
                st.warning("Completá tanto el Bot Token como el Chat ID")
            else:
                with st.spinner("Enviando mensaje de prueba..."):
                    r = _check_service("/config/check/telegram", {
                        "bot_token": tg_token,
                        "chat_id": tg_chat,
                    })
                _show_check_result(r)

    cfg_to_save.update({
        "TELEGRAM_BOT_TOKEN": tg_token,
        "TELEGRAM_CHAT_ID": tg_chat,
    })

    st.divider()

    # ── Sección 6: Budget Guard ───────────────────────────────────────────
    st.subheader("💰 Control de Presupuesto")
    st.caption("Solo aplica con OpenAI o Gemini. En Ollama el costo es $0 y se ignora automáticamente.")

    col_bg1, col_bg2, col_bg3 = st.columns(3)
    with col_bg1:
        budget_usd = st.number_input(
            "Presupuesto mensual (USD)",
            value=float(current_env.get("MONTHLY_BUDGET_USD", "50")),
            min_value=0.0, step=5.0, format="%.2f",
            help="0 = sin límite. Recomendado: $50 para empezar.",
            key="cfg_budget",
        )
    with col_bg2:
        alert_1 = st.slider(
            "Alerta 1 (% usado)",
            min_value=50, max_value=89, value=int(float(current_env.get("BUDGET_ALERT_THRESHOLD_1", "0.70")) * 100),
            key="cfg_alert1",
        )
    with col_bg3:
        alert_2 = st.slider(
            "Fallback model activar (% usado)",
            min_value=alert_1 + 1, max_value=99,
            value=int(float(current_env.get("BUDGET_ALERT_THRESHOLD_2", "0.90")) * 100),
            key="cfg_alert2",
        )

    cfg_to_save.update({
        "MONTHLY_BUDGET_USD": str(budget_usd),
        "BUDGET_ALERT_THRESHOLD_1": str(alert_1 / 100),
        "BUDGET_ALERT_THRESHOLD_2": str(alert_2 / 100),
    })

    st.divider()

    # ── Sección 7: Opciones avanzadas ─────────────────────────────────────
    st.subheader("🔧 Opciones Avanzadas")

    col_adv1, col_adv2 = st.columns(2)
    with col_adv1:
        enable_entities = st.toggle(
            "Extracción de entidades en ingesta (LightRAG)",
            value=current_env.get("ENABLE_ENTITY_EXTRACTION", "true").lower() == "true",
            help="Extrae entidades y relaciones de cada chunk usando LLM. ~$0.001/chunk con OpenAI. Gratis con Ollama.",
            key="cfg_entities",
        )
        enable_graph = st.toggle(
            "Activar Neo4j (Fase 2+)",
            value=current_env.get("ENABLE_GRAPH", "false").lower() == "true",
            help="Activa el grafo de conocimiento. Solo necesario cuando tenés +10.000 documentos.",
            key="cfg_graph",
        )
    with col_adv2:
        max_concurrent = st.number_input(
            "Generaciones concurrentes máximas",
            value=int(current_env.get("MAX_CONCURRENT_GENERATIONS", "5")),
            min_value=1, max_value=20,
            help="Más concurrencia = más rápido pero más riesgo de rate limits.",
            key="cfg_concurrent",
        )
        log_level = st.selectbox(
            "Nivel de logs",
            options=["DEBUG", "INFO", "WARNING", "ERROR"],
            index=["DEBUG", "INFO", "WARNING", "ERROR"].index(
                current_env.get("LOG_LEVEL", "INFO")
            ),
            key="cfg_log_level",
        )

    cfg_to_save.update({
        "ENABLE_ENTITY_EXTRACTION": "true" if enable_entities else "false",
        "ENABLE_GRAPH": "true" if enable_graph else "false",
        "MAX_CONCURRENT_GENERATIONS": str(max_concurrent),
        "LOG_LEVEL": log_level,
    })

    st.divider()

    # ── Botón de guardado ─────────────────────────────────────────────────
    st.subheader("💾 Guardar configuración")
    
    col_save1, col_save2 = st.columns([1, 3])
    with col_save1:
        if st.button("💾 Guardar en .env", type="primary", key="cfg_save"):
            try:
                # Filtrar valores vacíos que no queremos sobreescribir
                clean_cfg = {k: v for k, v in cfg_to_save.items() if v is not None}
                _write_env_file(clean_cfg)
                st.success("✅ Configuración guardada en `.env`. Reiniciá el servidor para aplicar los cambios.")
                st.info("💡 Para aplicar sin reiniciar, recargá esta página. Algunos cambios (como el proveedor LLM) requieren reiniciar el servidor FastAPI y Streamlit.")
            except Exception as e:
                st.error(f"❌ Error guardando: {e}")
    with col_save2:
        st.caption(
            "Los cambios en `.env` no se aplican automáticamente al proceso en ejecución. "
            "Necesitás reiniciar `uvicorn api.main:app` y `streamlit run dashboard/app.py` para que tomen efecto."
        )
    
    st.divider()

    # ── Sección 3: Reinicio de Servicios ─────────────────────────────────
    st.subheader(f"🔄 {t('config.restart_btn', lang)}")
    st.info(t("config.restart_info", lang))
    
    if st.button(t("config.restart_btn", lang), key="btn_restart_services"):
        _restart_services()

    # Mostrar el .env actual (sin passwords)
    with st.expander("👁️ Ver configuración actual (.env sanitizado)"):
        env_display = {
            k: ("***" if any(w in k.lower() for w in ["key", "password", "token", "secret"]) else v)
            for k, v in current_env.items()
        }
        st.json(env_display)