# POC: Graphiti Agent — RAG Híbrido con Despliegue por Fases

Esta prueba de concepto valida si la arquitectura **Graphiti + PostgreSQL/pgvector** es económicamente viable para producción. El sistema combina la velocidad de búsqueda vectorial de Postgres con la capacidad de razonamiento relacional de Graphiti/Neo4j, y está diseñado para activarse en etapas: arrancás barato con solo Postgres y activás el grafo cuando el negocio lo justifica.

---

## Índice

1. [¿Qué problema resuelve?](#qué-problema-resuelve)
2. [Arquitectura general](#arquitectura-general)
3. [Estrategia de despliegue por fases](#estrategia-de-despliegue-por-fases)
4. [Instalación y configuración](#instalación-y-configuración)
5. [Cómo correr el proyecto](#cómo-correr-el-proyecto)
6. [Estructura de archivos explicada](#estructura-de-archivos-explicada)
7. [Flujo de datos de punta a punta](#flujo-de-datos-de-punta-a-punta)
8. [Sistema de métricas y costos](#sistema-de-métricas-y-costos)
9. [Dashboard](#dashboard)
10. [Criterios de éxito (GO / OPTIMIZE / STOP)](#criterios-de-éxito)
11. [Preguntas frecuentes](#preguntas-frecuentes)

---

## ¿Qué problema resuelve?

El cliente tiene una base de conocimiento (transcripciones de podcasts, guías, playbooks) y necesita un agente que pueda responder preguntas usando esa información. La duda es: **¿cuánto cuesta realmente operar esto a escala?**

Este POC responde esa pregunta midiendo el costo exacto (en USD) de cada operación: ingestar un documento, hacer una búsqueda, generar un email. Con esos datos, el dashboard proyecta el gasto mensual y anual bajo distintos escenarios.

La arquitectura también resuelve un problema técnico: ¿cómo activar un knowledge graph sin tirar todo lo que ya está corriendo? La respuesta es la **migración por hidratación** — los documentos ya guardados en Postgres se pueden "hidratar" a Neo4j en un paso separado, sin re-ingestar archivos ni interrumpir el servicio.

---

## Arquitectura general

```
Documentos (.md)
      │
      ▼
┌─────────────────────────────┐
│   ingestion/ingest.py       │  Pipeline de ingesta
│                             │
│  1. Parsea frontmatter YAML │
│  2. Extrae entidades (gratis│  ← sin LLM, solo regex
│  3. Chunking por segmentos  │
│  4. Genera embeddings       │  ← OpenAI / Gemini
│  5. Guarda en Postgres      │
│  6. (Opcional) → Graphiti   │
└─────────────────────────────┘
         │                │
         ▼                ▼
  ┌────────────┐    ┌───────────┐
  │ PostgreSQL │    │  Neo4j    │
  │ (pgvector) │    │(Graphiti) │
  └────────────┘    └───────────┘
         │                │
         └───────┬─────────┘
                 ▼
        ┌─────────────────┐
        │  agent/tools.py │  Capa de búsqueda
        │                 │
        │ • vector_search │  ← cosine similarity
        │ • graph_search  │  ← relaciones/entidades
        │ • hybrid_search │  ← RRF (combina ambas)
        └─────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │ poc/content_    │  Generación de contenido
        │ generator.py    │  (emails, reels, historias)
        └─────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │ poc/token_      │  Tracking de costos
        │ tracker.py      │  (cada operación loguea USD)
        └─────────────────┘
```

**Stack tecnológico:**
- **Python 3.10+** con `asyncio` / `asyncpg` para I/O no bloqueante
- **PostgreSQL** con extensión `pgvector` para búsqueda vectorial
- **Neo4j** como base de datos del knowledge graph
- **Graphiti** (`graphiti-core`) para extracción automática de entidades y relaciones
- **OpenAI** o **Gemini** como proveedor de LLM y embeddings (configurable)
- **Streamlit** para el dashboard de métricas

---

## Estrategia de despliegue por fases

El proyecto está diseñado para crecer sin deuda técnica. Cada fase es un subset de la siguiente.

### Fase 1 — Vector Only (Lanzamiento productivo)

**Objetivo:** velocidad máxima, costo mínimo.

Solo se usa Postgres/pgvector. No se instala Neo4j, no se llama a Graphiti. El costo de ingesta es casi exclusivamente el embedding del texto (~$0.02/1M tokens).

```bash
# Ingestar documentos sin Graphiti
python -m poc.run_poc --ingest documents_to_index/ --skip-graphiti

# Búsquedas disponibles: vector y hybrid (RRF vector + full-text)
```

Cuándo usar esta fase: arranque del proyecto, validación de calidad de búsqueda, cuando el volumen de datos es bajo y las preguntas son "semánticas" (no relacionales).

---

### Fase 1.5 — Metadata Enrichment (sin costo extra)

**Objetivo:** preparar la base de datos para que la migración al grafo sea más barata y precisa.

Durante la ingesta normal (Fase 1), el pipeline ahora extrae automáticamente metadatos estructurados **sin gastar ni un token de LLM**:

- **Personas detectadas**: regex sobre el bloque "Participantes:" o nombres Nombre Apellido en el texto.
- **Empresas y herramientas**: palabras con mayúscula que aparecen ≥2 veces (Aerolab, Clay, Neo4j, etc.).
- **Segmentos temporales**: timestamps `[MM:SS]` del formato Novotalks, usados como límites de chunk.
- **Citas destacadas**: bloques `> "..."` del markdown.
- **`graphiti_ready_context`**: un string pre-formateado con todo lo anterior, listo para inyectar en Graphiti.

Ejemplo de lo que se genera automáticamente para un documento:

```
Document: Agustín Linenberg - Ventas y Startups | Category: Podcast |
People: Agustín Linenberg, Wences Casares, Dami, Tommy |
Organizations: Aerolab, Clay, Lemon Wallet, Neo4j |
Topics: Perfil Personal; Emprender por Accidente; Ventas por Relación
```

Este contexto se guarda en `documents.metadata` (columna JSONB). Cuando llegue Fase 2, Graphiti lo recibe como `source_description` en `add_episode()` y puede enfocar la extracción directamente en las entidades correctas, en lugar de inferirlas desde cero.

Cómo agregar frontmatter a tus documentos para enriquecer aún más los metadatos:

```yaml
---
title: "Agustín Linenberg: El Arte de Emprender"
category: Podcast
episode: "Novotalks #21"
guest: Agustín Linenberg
host: Dami, Tommy
date: 2024-03-15
---
```

---

### Fase 2 — Graph Hydration (Razonamiento profundo)

**Objetivo:** activar el knowledge graph para preguntas relacionales complejas.

En lugar de re-ingestar todos los archivos, se usa el script `poc/hydrate_graph.py` que lee los documentos ya guardados en Postgres y los envía a Graphiti. El proceso es **reanudable**: si se corta, la próxima ejecución continúa desde donde quedó usando el flag `metadata->>'graph_ingested'`.

```bash
# Preview: ver qué documentos se procesarían y con qué contexto
python -m poc.hydrate_graph --dry-run

# Ejecutar la migración
python -m poc.hydrate_graph

# Solo los primeros 10 documentos (para validar costos antes de escalar)
python -m poc.hydrate_graph --limit 10

# Re-procesar todos (ignorar el flag de ya-hidratado)
python -m poc.hydrate_graph --reset-flags
```

Una vez hidratado el grafo, están disponibles los tres modos de búsqueda:

```bash
# Búsqueda vectorial (rápida, semántica)
# Búsqueda en grafo (relaciones, entidades, hechos)
# Búsqueda híbrida (combina ambas con RRF)
python -m poc.run_poc --search
```

---

## Instalación y configuración

### Requisitos

- Python 3.10+
- Docker (para Postgres y Neo4j)

### 1. Clonar e instalar dependencias

```bash
git clone <repo>
cd poc-graphiti-agent
pip install -r requirements.txt
```

### 2. Levantar los servicios con Docker

```bash
docker-compose up -d
```

Esto levanta:
- **PostgreSQL** con extensión `pgvector` en el puerto 5432
- **Neo4j** en el puerto 7687 (bolt) y 7474 (browser web)

### 3. Configurar el archivo `.env`

Copiar `.env.example` y completar:

```env
# Proveedor LLM: "openai" o "gemini"
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Alternativa Gemini
# LLM_PROVIDER=gemini
# GEMINI_API_KEY=AI...

# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=graphiti_poc
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Neo4j (solo necesario en Fase 2)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Modelos (opcional, se auto-configuran según el proveedor)
# DEFAULT_MODEL=gpt-4o-mini
# EMBEDDING_MODEL=text-embedding-3-small
```

**Nota sobre modelos:** si `LLM_PROVIDER=gemini`, el sistema automáticamente usa `gemini-1.5-flash` y `text-embedding-004`. Si `LLM_PROVIDER=openai`, usa `gpt-5-mini` y `text-embedding-3-small`. Se pueden sobreescribir en el `.env`.

### 4. Verificar que todo funciona

```bash
python -m poc.check_system
```

Esto verifica conexión a Postgres, Neo4j (si está configurado), y que las API keys sean válidas.

---

## Cómo correr el proyecto

### Flujo completo (recomendado para el POC)

```bash
# Paso 1: Ingestar documentos (Fase 1 - sin grafo)
python -m poc.run_poc --ingest documents_to_index/ --skip-graphiti

# Paso 2: Correr búsquedas de prueba
python -m poc.run_poc --search --skip-graphiti

# Paso 3: Generar contenido de prueba
python -m poc.run_poc --generate

# Paso 4: Ver métricas en el dashboard
streamlit run dashboard/app.py
```

### Comandos individuales útiles

```bash
# Correr todo en un comando
python -m poc.run_poc --all --ingest documents_to_index/

# Limpiar la base de datos y los logs antes de un run fresco
python -m poc.run_poc --clear-db --clear-logs --ingest documents_to_index/ --skip-graphiti

# Saltear el health check (más rápido si ya sabés que todo está up)
python -m poc.run_poc --ingest documents_to_index/ --skip-checks --skip-graphiti

# Hidratación al grafo (Fase 2)
python -m poc.hydrate_graph --dry-run    # primero revisar
python -m poc.hydrate_graph              # ejecutar

# Solo búsquedas con grafo activado
python -m poc.run_poc --search
```

---

## Estructura de archivos explicada

```
poc-graphiti-agent/
│
├── agent/                      ← Capa de acceso a datos y búsqueda
│   ├── config.py               ← Re-exporta poc/config.py (backward compat)
│   ├── db_utils.py             ← Pool de conexiones Postgres + helpers CRUD
│   ├── gemini_client.py        ← Adaptador LLMClient de Graphiti para Gemini
│   ├── graph_utils.py          ← Wrapper de Graphiti/Neo4j
│   ├── models.py               ← Modelos Pydantic (SearchResult, etc.)
│   └── tools.py                ← Las 3 herramientas de búsqueda del agente
│
├── ingestion/                  ← Pipeline de procesamiento de documentos
│   ├── chunker.py              ← Divide texto en chunks con overlap
│   ├── embedder.py             ← Genera vectores (OpenAI o Gemini), singleton
│   └── ingest.py               ← Orquesta todo el pipeline de ingesta
│
├── poc/                        ← Scripts del POC y sistema de métricas
│   ├── config.py               ← Configuración central + precios de modelos
│   ├── token_tracker.py        ← Singleton thread-safe para contar tokens
│   ├── cost_calculator.py      ← Calcula USD a partir de tokens y modelo
│   ├── logging_utils.py        ← Loggers CSV para ingesta, búsqueda y generación
│   ├── content_generator.py    ← Genera contenido usando el LLM configurado
│   ├── hydrate_graph.py        ← Migración Postgres → Graphiti (Fase 2)
│   ├── run_poc.py              ← Script principal, entry point del POC
│   ├── check_system.py         ← Health check de conexiones y variables
│   ├── queries.py              ← 20 queries de prueba (vector, graph, hybrid)
│   └── prompts/                ← Templates de generación de contenido
│       ├── email.py
│       ├── historia.py
│       ├── reel_cta.py
│       └── reel_lead_magnet.py
│
├── dashboard/                  ← Interfaz visual Streamlit
│   ├── app.py                  ← App principal con tabs de métricas
│   └── utils.py                ← Helpers de visualización
│
├── sql/
│   └── schema.sql              ← Definición de tablas, índices y funciones SQL
│
├── documents_to_index/         ← Documentos de prueba (transcripciones Novotalks)
│   ├── agustin.md
│   ├── alex.md
│   ├── andres.md
│   ├── cristobal.md
│   └── lucas.md
│
├── tests/poc/
│   ├── test_token_tracker.py
│   └── test_cost_calculator.py
│
├── logs/                       ← Generado automáticamente al correr el POC
│   ├── ingesta_log.csv
│   ├── busqueda_log.csv
│   ├── generacion_log.csv
│   └── poc_execution.log
│
├── .env.example
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Flujo de datos de punta a punta

### Ingesta de un documento

Cuando llamás a `ingest_file("agustin.md")`, ocurre lo siguiente:

**1. Deduplicación**
Se calcula un hash SHA-256 del contenido crudo. Si ya existe un documento con ese hash en Postgres (`metadata->>'content_hash'`), se saltea. Esto permite re-ejecutar el script sin duplicar datos.

**2. Parseo de frontmatter**
Se extrae el bloque YAML entre `---`. Si no hay frontmatter, el doc se procesa igual usando el nombre de archivo como título.

**3. Extracción heurística de entidades (costo $0)**
Sin llamar a ningún LLM, se detectan:
- **Personas**: regex sobre el bloque "Participantes:" y patrones `Nombre Apellido:` en el texto.
- **Empresas/herramientas**: palabras con mayúscula inicial que aparecen ≥2 veces en el documento.
- **Segmentos temporales**: líneas con `[MM:SS]` usadas como límites de chunk.
- **Citas**: bloques `> "texto"` del formato markdown.

Todo esto se serializa como JSON y se guarda en `documents.metadata`, incluyendo el campo `graphiti_ready_context` (un string descriptivo listo para Graphiti).

**4. Chunking**
Si el documento tiene segmentos temporales detectados, se divide respetándolos como fronteras naturales. Cada sección temática `[12:30] - Ventas por Relación` se convierte en su propio chunk. Si no hay timestamps, se usa el `SemanticChunker` con overlap configurable.

**5. Embedding**
Se llama a `embedder.generate_embeddings_batch(chunks)` usando el singleton `get_embedder()`. Los tokens usados se registran en el `TokenTracker`.

**6. Persistencia en Postgres**
Se insertan:
- Un registro en `documents` con el contenido completo y toda la metadata.
- N registros en `chunks`, cada uno con su vector de embedding y su propia metadata (nombre del doc padre, índice, título del segmento).

**7. Ingesta en Graphiti (opcional)**
Si no se pasó `--skip-graphiti`, se llama a `GraphClient.add_episode()` con el contenido y el `graphiti_ready_context` como `source_description`. Graphiti procesa el texto, extrae nodos (entidades) y aristas (relaciones) y los guarda en Neo4j.

---

### Búsqueda

Hay tres modos:

**Vector search** (`vector_search_tool`):
1. Genera embedding de la query.
2. Ejecuta `SELECT ... ORDER BY embedding <=> $1 LIMIT $2` contra la tabla `chunks`.
3. Retorna los N chunks más similares con sus scores.

**Graph search** (`graph_search_tool`):
1. Llama a `GraphClient.search(query)`.
2. Graphiti ejecuta internamente un pipeline que combina búsqueda semántica en Neo4j con razonamiento sobre las relaciones del grafo.
3. Retorna resultados como strings descriptivos de hechos y relaciones.

**Hybrid search** (`hybrid_search_tool`):
1. Genera embedding de la query.
2. Llama a la función SQL `hybrid_search()` definida en `schema.sql`.
3. Esta función combina los rankings de similitud coseno (vector) y `ts_rank` (full-text) mediante **Reciprocal Rank Fusion (RRF)**.
4. RRF fusiona los dos rankings con la fórmula `1/(k + rank)` donde `k=60` por defecto, dándole peso configurable a cada señal.

---

### Hidratación del grafo (Fase 2)

`poc/hydrate_graph.py` orquesta la migración:

1. Llama a `get_documents_missing_from_graph()` — consulta Postgres filtrando por `metadata->>'graph_ingested' IS NOT TRUE`. Gracias al índice parcial en el schema, esta query es eficiente incluso con miles de documentos.
2. Por cada documento, extrae el `graphiti_ready_context` pre-calculado y lo inyecta como `source_description` en `GraphClient.add_episode()`.
3. Una vez procesado, llama a `mark_document_graph_ingested(doc_id)` que hace un `metadata || '{"graph_ingested": true}'::jsonb` — actualización atómica sin reescribir todo el JSONB.
4. Al final, muestra el costo total estimado y proyección mensual con decisión GO/OPTIMIZE/STOP.

---

## Sistema de métricas y costos

### TokenTracker (`poc/token_tracker.py`)

Singleton thread-safe (con `threading.Lock`) que vive durante toda la ejecución. Cada operación tiene un ciclo de vida:

```python
# Inicio de una operación
tracker.start_operation("ingest_agustin_1234", "ingestion")

# Registro de uso (puede llamarse múltiples veces por operación)
tracker.record_usage(op_id, tokens_in=450, tokens_out=0, model="text-embedding-3-small", detail_name="embedding")

# Fin y obtención de métricas acumuladas
metrics = tracker.end_operation(op_id)
# metrics.tokens_in, metrics.tokens_out, metrics.cost_usd, metrics.details
```

Si `tiktoken` está disponible, cuenta tokens con exactitud. Si no, usa la heurística `len(text) // 4`.

### CostCalculator (`poc/cost_calculator.py`)

Multiplica tokens por los precios definidos en `MODEL_PRICING` dentro de `poc/config.py`:

| Modelo | Input ($/1M tokens) | Output ($/1M tokens) |
|--------|---------------------|----------------------|
| `gpt-5-mini` | $0.080 | $0.320 |
| `gpt-4o-mini` | $0.150 | $0.600 |
| `gemini-1.5-flash` | $0.075 | $0.300 |
| `text-embedding-3-small` | $0.020 | — |
| `text-embedding-004` | $0.025 | — |

### Logs CSV (`logs/`)

Cada operación escribe en uno de tres archivos CSV thread-safe:

**`ingesta_log.csv`** — Una fila por documento ingestado:
`episodio_id, timestamp, nombre_archivo, longitud_palabras, chunks_creados, embeddings_tokens, entidades_detectadas, costo_total_usd, tiempo_seg`

**`busqueda_log.csv`** — Una fila por búsqueda ejecutada:
`query_id, timestamp, query_texto, tipo_busqueda, tokens_embedding, tokens_llm_in, tokens_llm_out, costo_total_usd, resultados_retornados, latencia_ms`

**`generacion_log.csv`** — Una fila por pieza de contenido generada:
`pieza_id, timestamp, formato, tema_base, tokens_contexto_in, tokens_prompt_in, tokens_out, modelo, provider, costo_usd, tiempo_seg, longitud_output_chars`

---

## Archivos clave en detalle

### `agent/db_utils.py`

Gestiona toda la interacción con PostgreSQL usando `asyncpg` con un pool de conexiones (min=2, max=10). Funciones principales:

- `DatabasePool.init_db()` — Crea las extensiones y aplica `schema.sql` si la tabla no existe. Detecta automáticamente si usar `vector(1536)` (OpenAI) o `vector(768)` (Gemini).
- `insert_document(title, source, content, metadata)` — Inserta en la tabla `documents` y retorna el UUID.
- `insert_chunks(doc_id, chunks, embeddings, chunk_metas)` — Inserta en batch en la tabla `chunks` usando `_fmt_vec()` para el formato correcto de pgvector.
- `document_exists_by_hash(hash)` — Consulta `metadata->>'content_hash'` para deduplicación.
- `get_documents_missing_from_graph(limit)` — Para `hydrate_graph.py`. Usa el índice parcial en `graph_ingested`.
- `mark_document_graph_ingested(doc_id)` — Actualiza el flag JSONB atómicamente.
- `vector_search(embedding, limit)` — Búsqueda cosine similarity.
- `hybrid_search(text, embedding, limit)` — Llama a la función SQL `hybrid_search()`.

### `agent/graph_utils.py`

Wrapper sobre `graphiti-core`. Se inicializa lazy (la primera vez que se llama a `get_client()`).

- Soporta OpenAI y Gemini como backend del LLM de Graphiti.
- `add_episode(content, source_reference, source_description)` — El parámetro `source_description` es el punto de entrada del contexto pre-calculado. Sin él, Graphiti gasta más tokens intentando inferir el tipo y contenido del documento.
- `search(query)` — Búsqueda semántica + relacional en el grafo.
- Estima el costo de cada episodio usando un ratio de 30% output/input (basado en el comportamiento real de Graphiti, más conservador que el 50% teórico).

### `ingestion/embedder.py`

Generador de embeddings con patrón singleton via `@lru_cache` en `get_embedder()`. Esto evita crear un nuevo cliente HTTP por cada búsqueda o ingesta.

- Para OpenAI: llama a `AsyncOpenAI.embeddings.create()` de forma nativa async.
- Para Gemini: `embed_content()` es sincrónico, por eso se envuelve en `asyncio.to_thread()` para no bloquear el event loop.
- `generate_embeddings_batch(texts)` — Procesa una lista de textos en un solo llamado API y retorna `(embeddings, total_tokens)`.

### `poc/config.py`

Configuración central usando Pydantic v2 `BaseSettings`. Lee del `.env` automáticamente. Usa un `@model_validator(mode="after")` para resolver los modelos por defecto de Gemini en el momento de construcción (no después), evitando mutaciones post-construcción que Pydantic v2 no permite.

### `sql/schema.sql`

Además de las tablas estándar, define:

- **Índice HNSW** en `chunks.embedding` para búsqueda aproximada de vecinos eficiente.
- **Índice GIN** en `content_tsvector` (columna generada) para full-text search.
- **Índice parcial** en `metadata->>'graph_ingested'` — solo indexa los documentos *no* hidratados, lo que lo mantiene pequeño y rápido.
- **Índice en `content_hash`** para deduplicación O(log n).
- **Función `hybrid_search()`** — implementa RRF en PL/pgSQL directamente en la base de datos.
- **Vista `v_document_summary`** — resumen por documento: cuántos chunks tiene, si fue hidratado al grafo, tokens totales.

---

## Dashboard

```bash
streamlit run dashboard/app.py
```

El dashboard tiene **seis tabs** principales:

1.  **📥 Ingesta**: Trigger para procesar nuevos documentos. Opción `--skip-graphiti` para iteración rápida.
2.  **🧠 Knowledge Base**: Visor de la base de datos. Muestra todos los documentos ingestados, conteo de chunks y metadata extraída. Permite filtrar por nombre.
3.  **🔍 Búsqueda**: Interfaz para probar Vector, Graph y Hybrid search. Incluye un **Debug Mode** para inspeccionar el JSON crudo y los scores RRF.
4.  **✨ Generación**: Templates predefinidos (Email, Historia, Reel) y un nuevo **Modo Custom** para experimentar con prompts libres.
5.  **📊 Analytics**: Métricas de costo total y gráficos de evolución temporal por tipo de operación (Ingesta, Búsqueda, Generación).
6.  **📈 Proyecciones**: Calculadora de ROI y estimación de costos mensuales según volumen esperado.

**Acciones de la Sidebar**:
- **🗑️ Clear Logs & DB**: Limpieza total para reiniciar pruebas.
- **💧 Re-hydrate Graph**: Forza la ingesta de documentos pendientes desde Postgres hacia Neo4j sin re-procesar embeddings.

---

## Criterios de éxito

El POC usa estos umbrales para decidir si escalar a producción:

| Decisión | Costo por episodio | Costo mensual | Costo anual |
|----------|--------------------|---------------|-------------|
| ✅ **GO** | < $0.40 | < $100 | < $1,500 |
| ⚠️ **OPTIMIZE** | $0.40 – $0.70 | $100 – $200 | $1,500 – $3,000 |
| 🛑 **STOP** | > $0.70 | > $200 | > $3,000 |

Un "episodio" es la ingesta de un documento completo a Graphiti (extracción de entidades + relaciones). La Fase 1 (solo embeddings) tiene un costo órdenes de magnitud menor y no entra en esta evaluación.

---

## Preguntas frecuentes

**¿Por qué Postgres y Neo4j en lugar de solo uno?**
Postgres con pgvector es excelente para búsqueda semántica pero no modela relaciones entre entidades. Neo4j/Graphiti es excelente para razonar sobre relaciones ("¿quién invirtió en qué empresa?", "¿qué personas comparten metodologías?") pero más lento y costoso. La arquitectura híbrida toma lo mejor de cada uno.

**¿Qué es Graphiti exactamente?**
`graphiti-core` es una librería open source que toma texto libre y automáticamente extrae entidades (personas, empresas, conceptos) y las relaciones entre ellas, guardándolas como nodos y aristas en Neo4j. Internamente llama al LLM configurado (OpenAI o Gemini) con varios prompts encadenados.

**¿Por qué se pre-calculan los metadatos en Fase 1 si Graphiti los va a extraer igual en Fase 2?**
Porque el `source_description` que se le pasa a `add_episode()` guía el LLM de Graphiti. Sin él, Graphiti necesita inferir el tipo de documento, sus participantes y sus temas desde cero — lo que consume prompts completos. Con el contexto pre-calculado, el LLM puede enfocarse directamente en extraer relaciones en lugar de descubrir información que ya tenemos. El ahorro estimado es 20–30% en tokens por episodio.

**¿Qué pasa si la hidratación se corta a mitad?**
`hydrate_graph.py` es reanudable. Cada documento procesado exitosamente recibe el flag `metadata->>'graph_ingested': true` en Postgres. La próxima ejecución consulta solo los documentos sin ese flag usando el índice parcial, así que no reprocesa nada.

**¿Cómo agrego más documentos?**
Ponelos en `documents_to_index/` y corrés el pipeline de nuevo. La deduplicación por hash SHA-256 garantiza que los documentos que ya están procesados no se vuelven a ingestar.

**¿Puedo usar solo Gemini?**
Sí. En el `.env` poner `LLM_PROVIDER=gemini` y `GEMINI_API_KEY=...`. El sistema automáticamente usa `gemini-1.5-flash` para el LLM y `text-embedding-004` (768 dimensiones) para embeddings. El schema se ajusta al ejecutar `init_db()`.

**¿Cómo corro los tests?**
```bash
pytest tests/poc/
```
Hay tests para `TokenTracker` (thread-safety, acumulación de costos) y `CostCalculator` (precios por modelo).