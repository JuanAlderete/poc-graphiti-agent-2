"""
i18n.py — Internationalization for the Graphiti POC Dashboard.
Supports: 'es' (Spanish) and 'en' (English).

Usage:
    from dashboard.i18n import t, LANGUAGES
    # Set language via st.session_state["lang"] = "es" | "en"
    label = t("sidebar.title")
"""

LANGUAGES = {"🇦🇷 Español": "es", "🇺🇸 English": "en"}

TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── App title ────────────────────────────────────────────────────────────
    "app.title": {
        "es": "🕸️ Graphiti POC — Centro de Control Agente",
        "en": "🕸️ Graphiti POC — Agentic Control Centre",
    },
    "app.page_title": {"es": "Dashboard Graphiti POC", "en": "Graphiti POC Dashboard"},

    # ── Sidebar ──────────────────────────────────────────────────────────────
    "sidebar.config": {"es": "⚙️ Configuración", "en": "⚙️ Configuration"},
    "sidebar.provider": {"es": "Proveedor LLM: **{p}**", "en": "LLM Provider: **{p}**"},
    "sidebar.actions": {"es": "Acciones", "en": "Actions"},
    "sidebar.clear_btn": {"es": "🗑️ Limpiar Logs & BD", "en": "🗑️ Clear Logs & DB"},
    "sidebar.clear_ok": {"es": "¡Logs y base de datos limpiados!", "en": "Logs and Database Cleared!"},
    "sidebar.hydrate_btn": {"es": "💧 Re-hidratar Grafo (Forzar)", "en": "💧 Re-hydrate Graph (Force)"},
    "sidebar.hydrate_help": {"es": "Envía todos los docs a Neo4j", "en": "Push all docs to Neo4j"},
    "sidebar.hydrate_spinner": {"es": "Hidratando grafo desde Postgres...", "en": "Hydrating Graph from Postgres..."},
    "sidebar.hydrate_ok": {"es": "¡Hidratación completa!", "en": "Hydration Complete!"},
    "sidebar.hydrate_err": {"es": "Error: {e}", "en": "Error: {e}"},
    "sidebar.language": {"es": "🌐 Idioma / Language", "en": "🌐 Language / Idioma"},

    # ── Tab names ────────────────────────────────────────────────────────────
    "tab.ingestion": {"es": "📥 Ingesta", "en": "📥 Ingestion"},
    "tab.kb": {"es": "🧠 Base de Conocimiento", "en": "🧠 Knowledge Base"},
    "tab.search": {"es": "🔍 Búsqueda", "en": "🔍 Search"},
    "tab.gen": {"es": "✨ Generación", "en": "✨ Generation"},
    "tab.analytics": {"es": "📊 Analíticas", "en": "📊 Analytics"},
    "tab.projections": {"es": "📈 Proyecciones", "en": "📈 Projections"},
    "tab.neo4j": {"es": "🔵 Grafo Neo4j", "en": "🔵 Neo4j Graph"},

    # ── Ingestion tab ────────────────────────────────────────────────────────
    "ingest.header": {"es": "Ingesta de Documentos", "en": "Document Ingestion"},
    "ingest.skip_graphiti": {
        "es": "⚡ Omitir Graphiti (solo Postgres)",
        "en": "⚡ Skip Graphiti (Postgres only)",
    },
    "ingest.skip_graphiti_help": {
        "es": "Más rápido — solo búsqueda vectorial. Destildá para construir el grafo también.",
        "en": "Faster — vector search only. Uncheck to also build the graph.",
    },
    "ingest.upload_header": {"es": "📤 Subir archivos", "en": "📤 Upload files"},
    "ingest.upload_label": {
        "es": "Arrastrá o seleccioná archivos para indexar",
        "en": "Drag or select files to index",
    },
    "ingest.upload_help": {
        "es": "Formatos soportados: .txt, .md, .csv, .pdf",
        "en": "Supported formats: .txt, .md, .csv, .pdf",
    },
    "ingest.upload_selected": {
        "es": "{n} archivo(s) seleccionado(s): {names}",
        "en": "{n} file(s) selected: {names}",
    },
    "ingest.upload_btn": {"es": "▶ Indexar archivos subidos", "en": "▶ Index uploaded files"},
    "ingest.upload_processing": {"es": "Procesando archivos…", "en": "Processing files…"},
    "ingest.upload_saving": {"es": "💾 Guardando archivos…", "en": "💾 Saving files…"},
    "ingest.upload_saved_ok": {"es": "  ✅ {name} guardado", "en": "  ✅ {name} saved"},
    "ingest.upload_saved_err": {"es": "  ❌ {name}: {e}", "en": "  ❌ {name}: {e}"},
    "ingest.upload_no_valid": {"es": "Sin archivos válidos", "en": "No valid files"},
    "ingest.upload_indexing": {"es": "🔄 Indexando {n} archivo(s)…", "en": "🔄 Indexing {n} file(s)…"},
    "ingest.upload_done": {"es": "✅ {n} archivo(s) indexados", "en": "✅ {n} file(s) indexed"},
    "ingest.upload_success": {
        "es": "Indexación completada. Revisá el tab **Base de Conocimiento** para verificar.",
        "en": "Indexing complete. Check the **Knowledge Base** tab to verify.",
    },
    "ingest.upload_ingest_err": {"es": "Error: {e}", "en": "Error: {e}"},
    "ingest.dir_header": {"es": "📁 Indexar directorio", "en": "📁 Index directory"},
    "ingest.dir_label": {"es": "Ruta del directorio", "en": "Directory path"},
    "ingest.dir_btn": {"es": "▶ Indexar directorio", "en": "▶ Index directory"},
    "ingest.dir_not_found": {"es": "Directorio '{d}' no encontrado.", "en": "Directory '{d}' not found."},
    "ingest.dir_spinner": {"es": "Ingestando documentos…", "en": "Ingesting documents…"},
    "ingest.dir_init": {"es": "Inicializando pipeline…", "en": "Initialising pipeline…"},
    "ingest.dir_done": {"es": "¡Ingesta completa!", "en": "Ingestion Complete!"},
    "ingest.dir_success": {"es": "Documentos indexados desde `{d}`.", "en": "Successfully ingested documents from `{d}`."},
    "ingest.dir_failed": {"es": "Error de Ingesta", "en": "Ingestion Failed"},
    "ingest.dir_err": {"es": "Error: {e}", "en": "Error: {e}"},

    # ── Knowledge Base tab ───────────────────────────────────────────────────
    "kb.header": {"es": "🧠 Base de Conocimiento", "en": "🧠 Knowledge Base"},
    "kb.refresh": {"es": "🔄 Actualizar BD", "en": "🔄 Refresh DB"},
    "kb.no_docs": {"es": "No hay documentos en la base de datos.", "en": "No documents found in database."},
    "kb.total_docs": {"es": "Total Documentos", "en": "Total Documents"},
    "kb.total_chunks": {"es": "Total Chunks", "en": "Total Chunks"},
    "kb.filter": {"es": "Filtrar por nombre/título", "en": "Filter by filename/title"},
    "kb.col_ingested": {"es": "Ingestado en", "en": "Ingested At"},
    "kb.col_metadata": {"es": "Metadatos", "en": "Metadata"},
    "kb.col_chunks": {"es": "Chunks", "en": "Chunks"},
    "kb.col_path": {"es": "Ruta", "en": "File Path"},
    "kb.col_title": {"es": "Título", "en": "Title"},
    "kb.error": {"es": "Error al cargar la base de conocimiento: {e}", "en": "Error fetching knowledge base: {e}"},

    # ── Search tab ───────────────────────────────────────────────────────────
    "search.header": {"es": "Búsqueda por Grafo y Vector", "en": "Graph & Vector Search"},
    "search.query_label": {"es": "Consulta de búsqueda", "en": "Search Query"},
    "search.query_default": {
        "es": "Estrategias de crecimiento para startups B2B",
        "en": "Growth strategies for B2B startups",
    },
    "search.type_label": {"es": "Tipo de búsqueda", "en": "Search Type"},
    "search.types": {"es": ["Vector", "Grafo", "Híbrido"], "en": ["Vector", "Graph", "Hybrid"]},
    "search.btn": {"es": "🔍 Buscar", "en": "🔍 Run Search"},
    "search.spinner": {"es": "Ejecutando búsqueda {t}…", "en": "Running {t} search…"},
    "search.results": {"es": "{n} resultado(s)", "en": "{n} result(s)"},
    "search.debug": {"es": "Ver JSON crudo (Modo Debug)", "en": "Show Raw JSON (Debug Mode)"},
    "search.score": {"es": "puntaje", "en": "score"},
    "search.raw_data": {"es": "Datos crudos:", "en": "Raw Result Data:"},
    "search.metadata": {"es": "Metadatos:", "en": "Metadata:"},
    "search.error": {"es": "Error en búsqueda: {e}", "en": "Search failed: {e}"},

    # ── Generation tab ───────────────────────────────────────────────────────
    "gen.header": {"es": "Generación de Contenido", "en": "Content Generation"},
    "gen.template_label": {"es": "Seleccionar plantilla", "en": "Select Template"},
    "gen.templates": {
        "es": ["Email Frío", "Historia de Startup", "Reel de Instagram", "Personalizado"],
        "en": ["Cold Email", "Startup Story", "Instagram Reel", "Custom"],
    },
    "gen.topic": {"es": "Tema", "en": "Topic"},
    "gen.objective": {"es": "Objetivo", "en": "Objective"},
    "gen.context": {"es": "Contexto", "en": "Context"},
    "gen.tone": {"es": "Tono", "en": "Tone"},
    "gen.cta": {"es": "CTA", "en": "CTA"},
    "gen.system_prompt": {"es": "System Prompt", "en": "System Prompt"},
    "gen.prompt": {"es": "Prompt", "en": "Prompt"},
    "gen.btn": {"es": "✨ Generar Contenido", "en": "✨ Generate Content"},
    "gen.spinner": {"es": "Generando…", "en": "Generating…"},
    "gen.result_header": {"es": "Contenido Generado", "en": "Generated Content"},
    "gen.generated_with": {"es": "Generado con **{p}**", "en": "Generated using **{p}**"},
    "gen.error": {"es": "Error de generación: {e}", "en": "Generation failed: {e}"},
    "gen.agent_header": {"es": "🤖 Generación con Agentes Estructurados", "en": "🤖 Structured Agent Generation"},
    "gen.agent_caption": {
        "es": "Output estructurado por formato con campos específicos (Hook, Script, CTA, etc.)",
        "en": "Structured output per format with specific fields (Hook, Script, CTA, etc.)",
    },
    "gen.agent_format": {"es": "Formato", "en": "Format"},
    "gen.agent_topic": {"es": "Tema", "en": "Topic"},
    "gen.agent_topic_default": {"es": "Validación de ideas de negocio", "en": "Business idea validation"},
    "gen.agent_context": {
        "es": "Contexto (dejar vacío para búsqueda automática)",
        "en": "Context (leave empty for auto search)",
    },
    "gen.agent_btn": {"es": "🚀 Generar con Agente Estructurado", "en": "🚀 Generate with Structured Agent"},
    "gen.agent_spinner": {"es": "Generando {f}…", "en": "Generating {f}…"},

    # ── Generation: template-specific fields ─────────────────────────────────
    "gen.email_topic_default": {"es": "SaaS Growth", "en": "SaaS Growth"},
    "gen.email_objective_default": {"es": "Agendar una demo", "en": "Schedule a demo"},
    "gen.email_context_default": {"es": "Contexto simulado sobre crecimiento B2B…", "en": "Simulated context about B2B growth…"},
    "gen.historia_topic_default": {"es": "El origen de una startup", "en": "The origin of a startup"},
    "gen.historia_tone_default": {"es": "Inspirador", "en": "Inspiring"},
    "gen.historia_context_default": {"es": "Fundadores en un garaje…", "en": "Founders in a garage…"},
    "gen.historia_tipo_label": {"es": "Tipo de historia", "en": "Story type"},
    "gen.historia_tipo_options": {
        "es": ["educativa", "autoridad", "prueba_social", "cta"],
        "en": ["educational", "authority", "social_proof", "cta"],
    },
    "gen.reel_topic_default": {"es": "Productivity Hacks", "en": "Productivity Hacks"},
    "gen.reel_cta_default": {"es": "Sígueme para más", "en": "Follow me for more"},
    "gen.reel_context_default": {"es": "Uso de herramientas AI…", "en": "Using AI tools…"},
    "gen.custom_topic_default": {"es": "Mi Nuevo Contenido", "en": "My New Content"},
    "gen.custom_system_default": {"es": "Eres un experto en marketing digital.", "en": "You are a digital marketing expert."},
    "gen.custom_prompt_default": {"es": "Escribe un post sobre...", "en": "Write a post about..."},
    "gen.lead_magnet_label": {"es": "Lead Magnet", "en": "Lead Magnet"},
    "gen.lead_magnet_default": {"es": "Checklist gratuita", "en": "Free checklist"},
    "gen.ads_tipo_label": {"es": "Tipo de anuncio", "en": "Ad type"},
    "gen.ads_tipo_options": {
        "es": ["awareness", "consideration", "conversion"],
        "en": ["awareness", "consideration", "conversion"],
    },
    "gen.no_context_fallback": {"es": "Sin contexto disponible.", "en": "No context available."},
    "gen.reel_cta_agent_default": {"es": "Sígueme para más", "en": "Follow me for more"},
    "gen.historia_tone_agent_default": {"es": "Educativo y cercano", "en": "Educational and relatable"},
    "gen.email_objective_agent_default": {"es": "Generar interés", "en": "Generate interest"},
    "gen.agent_budget_critical": {
        "es": "⚠️ Budget crítico: {pct}% usado. Fallback: {m}",
        "en": "⚠️ Critical budget: {pct}% used. Fallback: {m}",
    },
    "gen.agent_budget_warn": {
        "es": "💡 Budget al {pct}%. Gasto: ${spent} / ${budget}",
        "en": "💡 Budget at {pct}%. Spent: ${spent} / ${budget}",
    },
    "gen.agent_qa": {"es": "✅ QA {r} | Costo: ${c}", "en": "✅ QA {r} | Cost: ${c}"},
    "gen.agent_qa_notes": {"es": "QA notas: {n}", "en": "QA notes: {n}"},
    "gen.agent_error": {"es": "Error: {e}", "en": "Error: {e}"},

    # ── Analytics tab ────────────────────────────────────────────────────────
    "analytics.header": {"es": "Analytics del Sistema", "en": "System Analytics"},
    "analytics.refresh": {"es": "🔄 Actualizar", "en": "🔄 Refresh"},
    "analytics.total_cost": {"es": "Costo Total (Est.)", "en": "Total Cost (Est)"},
    "analytics.files_ingested": {"es": "Archivos Ingestados", "en": "Files Ingested"},
    "analytics.searches": {"es": "Búsquedas", "en": "Searches Run"},
    "analytics.generated": {"es": "Piezas Generadas", "en": "Pieces Generated"},
    "analytics.cost_evolution": {"es": "Evolución de Costos", "en": "Cost Evolution"},
    "analytics.axis_time": {"es": "Tiempo", "en": "Time"},
    "analytics.axis_cost": {"es": "Costo (USD)", "en": "Cost (USD)"},
    "analytics.axis_type": {"es": "Tipo", "en": "Type"},
    "analytics.no_cost_data": {"es": "Sin datos de costos.", "en": "No cost data to display."},
    "analytics.log_ingestion": {"es": "Log de Ingesta", "en": "Ingestion Log"},
    "analytics.log_search": {"es": "Log de Búsqueda", "en": "Search Log"},
    "analytics.log_gen": {"es": "Log de Generación", "en": "Generation Log"},
    "analytics.no_ingest_logs": {"es": "Sin logs de ingesta.", "en": "No ingestion logs yet."},
    "analytics.no_search_logs": {"es": "Sin logs de búsqueda.", "en": "No search logs yet."},
    "analytics.no_gen_logs": {"es": "Sin logs de generación.", "en": "No generation logs yet."},
    "analytics.budget_header": {"es": "💰 Estado del Presupuesto", "en": "💰 Budget Status"},
    "analytics.budget_spent": {"es": "Gastado este mes", "en": "Spent this month"},
    "analytics.budget_total": {"es": "Budget mensual", "en": "Monthly budget"},
    "analytics.budget_pct": {"es": "% Usado", "en": "% Used"},
    "analytics.budget_projection": {"es": "Proyección mensual", "en": "Monthly projection"},
    "analytics.budget_fallback": {"es": "🔴 Modelo fallback activo: **{m}**", "en": "🔴 Fallback model active: **{m}**"},
    "analytics.budget_warn": {"es": "🟡 Budget al {pct}% — modelo: **{m}**", "en": "🟡 Budget at {pct}% — model: **{m}**"},
    "analytics.budget_ok": {"es": "🟢 Budget OK — modelo activo: **{m}**", "en": "🟢 Budget OK — active model: **{m}**"},
    "analytics.budget_unavail": {"es": "Budget tracking no disponible: {e}", "en": "Budget tracking unavailable: {e}"},

    # ── Projections tab ──────────────────────────────────────────────────────
    "proj.header": {"es": "📈 Proyecciones de Costo", "en": "📈 Cost Projections"},
    "proj.caption": {
        "es": "Ajustá los parámetros para simular distintos escenarios de uso.",
        "en": "Adjust parameters to simulate different usage scenarios.",
    },
    "proj.docs_month": {"es": "Documentos / mes", "en": "Documents / month"},
    "proj.queries_month": {"es": "Búsquedas / mes", "en": "Searches / month"},
    "proj.pieces_month": {"es": "Piezas generadas / mes", "en": "Generated pieces / month"},
    "proj.ingest_month": {"es": "Ingesta / mes", "en": "Ingestion / month"},
    "proj.search_month": {"es": "Búsquedas / mes", "en": "Searches / month"},
    "proj.gen_month": {"es": "Generación / mes", "en": "Generation / month"},
    "proj.total_month": {"es": "**Total / mes**", "en": "**Total / month**"},
    "proj.annual": {"es": "💰 Costo anual proyectado", "en": "💰 Projected annual cost"},
    "proj.go": {"es": "✅ **GO** — Costo mensual por debajo de $100", "en": "✅ **GO** — Monthly cost below $100"},
    "proj.optimize": {
        "es": "⚠️ **OPTIMIZAR** — Costo entre $100–$200/mes.",
        "en": "⚠️ **OPTIMIZE** — Cost between $100–$200/month.",
    },
    "proj.stop": {
        "es": "🛑 **DETENER** — Costo superior a $200/mes. Arquitectura no viable.",
        "en": "🛑 **STOP** — Cost exceeds $200/month. Architecture not viable.",
    },
    "proj.unit_costs": {"es": "Ver costos unitarios utilizados", "en": "View unit costs used"},
    "proj.source_logs": {"es": "desde logs", "en": "from logs"},
    "proj.source_default": {"es": "estimaciones por defecto", "en": "default estimates"},

    # ── Neo4j tab ────────────────────────────────────────────────────────────
    "neo4j.header": {"es": "Explorador de Grafo Neo4j", "en": "Neo4j Graph Explorer"},
    "neo4j.connected": {"es": "Conectado a: `{uri}`", "en": "Connected to: `{uri}`"},
    "neo4j.error": {"es": "No se puede conectar a Neo4j: {e}", "en": "Cannot connect to Neo4j: {e}"},
    "neo4j.nodes": {"es": "Nodos", "en": "Nodes"},
    "neo4j.rels": {"es": "Relaciones", "en": "Relationships"},
    "neo4j.episodes": {"es": "Episodios", "en": "Episodes"},
    "neo4j.entity_types": {"es": "Tipos de Entidades", "en": "Entity Types"},
    "neo4j.subtab_graph": {"es": "Grafo Interactivo", "en": "Interactive Graph"},
    "neo4j.subtab_episodes": {"es": "Episodios", "en": "Episodes"},
    "neo4j.subtab_details": {"es": "Detalles", "en": "Details"},
    "neo4j.subtab_query": {"es": "Query Cypher", "en": "Cypher Query"},
    "neo4j.filter_label": {"es": "Filtrar por label", "en": "Filter by label"},
    "neo4j.filter_all": {"es": "Todos", "en": "All"},
    "neo4j.max_nodes": {"es": "Máx. nodos", "en": "Max nodes"},
    "neo4j.physics": {"es": "Física", "en": "Physics"},
    "neo4j.no_nodes": {"es": "No hay nodos en la base de datos.", "en": "No nodes in database."},
    "neo4j.building": {"es": "Construyendo grafo...", "en": "Building graph..."},
    "neo4j.showing": {"es": "Mostrando {n} nodos, {r} relaciones", "en": "Showing {n} nodes, {r} relationships"},
    "neo4j.label": {"es": "Etiqueta", "en": "Label"},
    "neo4j.unknown": {"es": "Desconocido", "en": "Unknown"},
    "neo4j.episodes_header": {"es": "Episodios ingestados ({n})", "en": "Ingested Episodes ({n})"},
    "neo4j.no_episodes": {"es": "No se encontraron nodos episódicos.", "en": "No episodic nodes found."},
    "neo4j.node_labels": {"es": "Labels de Nodos", "en": "Node Labels"},
    "neo4j.rel_types": {"es": "Tipos de Relación", "en": "Relationship Types"},
    "neo4j.cypher_header": {"es": "Ejecutar Query Cypher", "en": "Run Cypher Query"},
    "neo4j.cypher_label": {"es": "Cypher", "en": "Cypher"},
    "neo4j.cypher_btn": {"es": "Ejecutar", "en": "Execute"},
    "neo4j.cypher_no_results": {"es": "La query no devolvió resultados.", "en": "Query returned no results."},
    "neo4j.cypher_error": {"es": "Error en query: {e}", "en": "Query error: {e}"},
}


def t(key: str, lang: str = "es", **kwargs) -> str:
    """
    Translate a key to the given language.
    Extra kwargs are used for string formatting: t("key.with.{x}", x="value").
    """
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return f"[{key}]"  # missing key fallback
    text = entry.get(lang, entry.get("en", f"[{key}]"))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text
