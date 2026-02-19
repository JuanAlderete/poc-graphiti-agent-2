import streamlit as st
import asyncio
import os
import pandas as pd
import time
from poc.run_poc import run_ingestion
from agent.tools import vector_search_tool, graph_search_tool, hybrid_search_tool
from poc.content_generator import get_content_generator
from poc.prompts import email, historia, reel_cta
from poc.logging_utils import clear_all_logs, ingestion_logger, search_logger, generation_logger
from agent.db_utils import DatabasePool

# Page Config
st.set_page_config(
    page_title="Graphiti POC Dashboard",
    page_icon="🕸️",
    layout="wide"
)

# Title
st.title("🕸️ Graphiti POC - Agentic Control Center")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Provider Check
    provider = os.getenv("LLM_PROVIDER", "openai").upper()
    if provider == "GEMINI":
        st.info(f"LLM Provider: **{provider}** 🟢")
    else:
        st.warning(f"LLM Provider: **{provider}** (Check .env)")
    
    st.divider()
    
    st.subheader("Actions")
    if st.button("🗑️ Clear Logs & DB", type="primary"):
        clear_all_logs()
        asyncio.run(DatabasePool.clear_database())
        st.success("Logs and Database Cleared!")
        time.sleep(1)
        st.rerun()

# Tabs
tab_ingest, tab_search, tab_gen, tab_analytics = st.tabs([
    "📥 Ingestion", 
    "🔍 Search", 
    "✨ Generation", 
    "📊 Analytics"
])

# --- TAB 1: INGESTION ---
with tab_ingest:
    st.header("Document Ingestion")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        docs_dir = st.text_input("Directory Path", value="documents_to_index")
    with col2:
        skip_graphiti = st.checkbox("Skip Graphiti (Postgres Only)", value=True, help="Faster, Vector only.")
        
    if st.button("Start Ingestion"):
        if not os.path.exists(docs_dir):
            st.error(f"Directory '{docs_dir}' not found.")
        else:
            with st.status("Ingesting documents...", expanded=True) as status:
                st.write("Initializing Pipeline...")
                try:
                    # Run async ingestion
                    asyncio.run(run_ingestion(docs_dir, skip_graphiti=skip_graphiti))
                    status.update(label="Ingestion Complete!", state="complete", expanded=False)
                    st.success(f"Successfully ingested documents from `{docs_dir}`.")
                except Exception as e:
                    status.update(label="Ingestion Failed", state="error")
                    st.error(f"Error: {e}")

# --- TAB 2: SEARCH ---
with tab_search:
    st.header("Graph & Vector Search")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_area("Search Query", "Estrategias de crecimiento para startups B2B")
    with col2:
        search_type = st.radio("Search Type", ["Vector", "Graph", "Hybrid"], index=2)
    
    if st.button("Run Search"):
        with st.spinner(f"Running {search_type} search..."):
            try:
                results = ""
                if search_type == "Vector":
                    results = asyncio.run(vector_search_tool(query))
                elif search_type == "Graph":
                    results = asyncio.run(graph_search_tool(query))
                elif search_type == "Hybrid":
                    results = asyncio.run(hybrid_search_tool(query))
                
                st.subheader("Results")
                st.markdown(results)
            except Exception as e:
                st.error(f"Search failed: {e}")

# --- TAB 3: GENERATION ---
with tab_gen:
    st.header("Content Generation")
    
    template_type = st.selectbox("Select Template", ["Cold Email", "Startup Story", "Instagram Reel"])
    
    prompt = ""
    system_prompt = ""
    
    if template_type == "Cold Email":
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("Topic", "SaaS Growth")
            objective = st.text_input("Objective", "Agendar una demo")
        with col2:
             context = st.text_area("Context", "Contexto simulado sobre crecimiento B2B...")
        
        system_prompt = email.SYSTEM_PROMPT
        prompt = email.PROMPT_TEMPLATE.format(topic=topic, context=context, objective=objective)
        
    elif template_type == "Startup Story":
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("Topic", "El origen de una startup")
            tone = st.text_input("Tone", "Inspirador")
        with col2:
            context = st.text_area("Context", "Fundadores en un garaje...", height=100)
        
        system_prompt = historia.SYSTEM_PROMPT
        prompt = historia.PROMPT_TEMPLATE.format(topic=topic, context=context, tone=tone)
        
    elif template_type == "Instagram Reel":
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("Topic", "Productivity Hacks")
            cta = st.text_input("CTA", "Sígueme para más")
        with col2:
            context = st.text_input("Context", "Uso de herramientas AI...")
        
        system_prompt = reel_cta.SYSTEM_PROMPT
        prompt = reel_cta.PROMPT_TEMPLATE.format(topic=topic, context=context, cta=cta)

    if st.button("Generate Content"):
        with st.spinner("Generating..."):
            try:
                generator = get_content_generator()
                content = asyncio.run(generator.generate(prompt, system_prompt))
                st.subheader("Generated Content")
                st.markdown(content)
                st.divider()
                st.caption(f"Generated using **{os.getenv('LLM_PROVIDER', 'openai')}**")
            except Exception as e:
                st.error(f"Generation failed: {e}")

# --- TAB 4: ANALYTICS ---
with tab_analytics:
    st.header("System Analytics")
    
    # Reload button
    if st.button("🔄 Refresh Data"):
        st.rerun()

    # Helper to load logs
    def load_log(filename):
        path = os.path.join("logs", filename)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                return pd.read_csv(path)
            except pd.errors.EmptyDataError:
                return pd.DataFrame()
        return pd.DataFrame()

    # Load Data
    df_ingest = load_log("ingesta_log.csv")
    df_search = load_log("busqueda_log.csv")
    df_gen = load_log("generacion_log.csv")
    
    # Metrics
    st.subheader("Overview")
    col1, col2, col3 = st.columns(3)
    
    total_cost = 0.0
    
    if not df_ingest.empty and "costo_total_usd" in df_ingest.columns:
        total_cost += df_ingest["costo_total_usd"].sum()
        
    if not df_gen.empty and "costo_usd" in df_gen.columns:
         total_cost += df_gen["costo_usd"].sum()
         
    col1.metric("Total Cost (Est)", f"${total_cost:.4f}")
    col2.metric("Ingested Files", len(df_ingest) if not df_ingest.empty else 0)
    col3.metric("Generated Pieces", len(df_gen) if not df_gen.empty else 0)
    
    st.divider()
    
    # Visuals
    tab_logs_1, tab_logs_2, tab_logs_3 = st.tabs(["Ingestion Logs", "Generation Logs", "Search Logs"])
    
    with tab_logs_1:
        if not df_ingest.empty:
            st.dataframe(df_ingest)
            if "tiempo_seg" in df_ingest.columns:
                st.bar_chart(df_ingest, x="nombre_archivo", y="tiempo_seg")
        else:
            st.info("No ingestion logs found.")
            
    with tab_logs_2:
        if not df_gen.empty:
            st.dataframe(df_gen)
            if "tokens_out" in df_gen.columns and "modelo" in df_gen.columns:
                 st.scatter_chart(df_gen, x="tokens_out", y="tiempo_seg", color="modelo")
        else:
            st.info("No generation logs found.")

    with tab_logs_3:
        if not df_search.empty:
            st.dataframe(df_search)
        else:
            st.info("No search logs found.")
