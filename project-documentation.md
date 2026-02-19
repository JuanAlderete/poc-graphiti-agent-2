# Documentación del Funcionamiento del Proyecto

Este documento describe en detalle el funcionamiento del proyecto **poc-graphiti-agent**, reflejando la arquitectura actual tras la limpieza y refactorización.

## Visión General

El proyecto es un sistema de **RAG Agéntico (Retrieval-Augmented Generation)** que combina búsqueda vectorial y Grafos de Conocimiento (Knowledge Graph) utilizando **Graphiti** y **Neo4j**. Permite ingestar documentos, procesarlos para extraer entidades y relaciones, y luego consultarlos mediante un agente inteligente o scripts de prueba.

---

## 1. Módulo `agent/` (El Cerebro)

Este directorio contiene la lógica principal del agente, las herramientas y la capa de datos.

### `agent/utils/` (Utilidades Compartidas)
Contiene módulos de soporte utilizados por todo el sistema (anteriormente en `poc/`).
- **`token_tracker.py`**: Singleton para contar tokens usados en diferentes operaciones (LLM, Graphiti).
- **`cost_calculator.py`**: Calcula el precio estimado en USD basado en modelos de OpenAI.
- **`logging_utils.py`**: Funciones para inicializar y escribir logs en CSV.
- **`config.py`**: Constantes y configuración centralizada.

### `agent/db_utils.py`
Manejo de **PostgreSQL** (usando `asyncpg` y `pgvector`).
- **`DatabasePool`**: Gestiona el pool de conexiones.
- **`vector_search`**: Ejecuta consultas SQL de similitud vectorial (`ORDER BY embedding <=> query_embedding`).
- **`hybrid_search`**: Combina similitud de coseno con búsqueda por palabras clave (`tsvector`).

### `agent/graph_utils.py`
Manejo de **Neo4j** y **Graphiti**.
- **`GraphitiClient`**: Wrapper sobre la librería `graphiti_core`.
- **`initialize`**: Conecta a Neo4j y configura los clientes de OpenAI.
- **`add_episode`**: Inserta información en el grafo. Graphiti procesa el texto y extrae nodos/aristas automáticamente.
- **`search`**: Realiza búsquedas semánticas/estructuradas en el grafo.

### `agent/tools.py`
Implementación de herramientas para el agente (usadas también por scripts de prueba).
- **`vector_search_tool`**: Genera embedding de la query y consulta Postgres.
- **`graph_search_tool`**: Consulta Graphiti para hechos y relaciones.
- **`hybrid_search_tool`**: Combina ambas estrategias.

### `agent/models.py`
Define los modelos de datos Pydantic para el sistema (ej. `IngestionConfig`, `SearchResult`).

---

## 2. Módulo `ingestion/` (La Boca)

Encargado de leer archivos, procesarlos y guardarlos en las bases de datos.

### `ingestion/ingest.py`
Script principal de ingesta (`python -m ingestion.ingest`).
- **`DocumentIngestionPipeline`**: Orquesta el flujo:
    1.  **Lectura**: Carga archivos Markdown.
    2.  **Chunking**: Llama a `chunker.py`.
    3.  **Embedding**: Llama a `embedder.py`.
    4.  **Guardado SQL**: Persiste documentos y vectores en Postgres.
    5.  **Guardado Grafo**: Envía chunks a Graphiti (Neo4j).

### `ingestion/chunker.py`
- **`SemanticChunker`**: Divide texto inteligentemente (usando LLM si es necesario) para no cortar ideas.
- **`SimpleChunker`**: División por caracteres/líneas (fallback).

### `ingestion/embedder.py`
- **`EmbeddingGenerator`**: Genera vectores usando OpenAI (`text-embedding-3-small`). Incluye caché y manejo de rate limits.

---

## 3. Módulo `poc/` (Proof of Concept & Scripts)

Scripts de ejecución, prueba y validación del sistema.

### `poc/run_poc.py`
**Entrypoint Principal**. Script "todo en uno" para ejecutar el flujo completo.
- **Uso**: `python poc/run_poc.py --all --documents "ruta/docs" --clean`
- **Funcionalidad**:
    1.  Ejecuta **System Health Check**.
    2.  Llama a `ingestion/ingest.py` (subprocess).
    3.  Ejecuta pruebas de búsqueda (`test_search`).
    4.  Ejecuta generación de contenido (`test_generation`).
    5.  Limpia y rota logs.

### `poc/check_system.py` (System Health Check)
Script de verificación previa al vuelo.
- **Verifica**:
    - Variables de entorno (`.env`).
    - Estado de Docker.
    - Contenedores activos (`postgres_vector` / `agentic-postgres`).
    - Conectividad real a Postgres y Neo4j.
- **Integración**: Se ejecuta automáticamente al inicio de `run_poc.py` (saltable con `--skip-checks`).

### `poc/content_generator.py`
Módulo para generar contenido (artículos, posts) usando la información recuperada del RAG.
- Usa `prompts/` para definir plantillas de generación.

---

## 4. Directorio `archive/` (Código Archivado)

Como parte de la limpieza agresiva, se movieron aquí los componentes no esenciales para el POC actual:
- **`agent/api.py`**: API FastAPI (no utilizada en la ejecución por CLI).
- **`agent/agent.py`**: Clase `Agente` principal (reemplazada por lógica simplificada en scripts).
- **`cli.py`**: CLI interactivo antiguo.
- **`dashboard/`**: App de Streamlit.
- **`tests/`**: Tests unitarios antiguos.

Estos archivos se conservan por referencia histórica pero no son cargados por el sistema actual.