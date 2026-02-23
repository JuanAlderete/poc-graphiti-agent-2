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
9. [Optimizaciones de costo implementadas](#optimizaciones-de-costo-implementadas)
10. [Criterios de éxito (GO / OPTIMIZE / STOP)](#criterios-de-éxito)
11. [Preguntas frecuentes](#preguntas-frecuentes)

---

## ¿Qué problema resuelve?

El cliente tiene una base de conocimiento (transcripciones de podcasts, guías, playbooks) y necesita un agente que pueda responder preguntas usando esa información. La duda es: **¿cuánto cuesta realmente operar esto a escala?**

Este POC responde esa pregunta midiendo el costo exacto (en USD) de cada operación: ingestar un documento, hacer una búsqueda, generar un email. Con esos datos, el sistema proyecta el gasto mensual y anual bajo distintos escenarios.

La arquitectura también resuelve un problema técnico: ¿cómo activar un knowledge graph sin tirar todo lo que ya está corriendo? La respuesta es la **migración por hidratación** — los documentos ya guardados en Postgres se pueden "hidratar" a Neo4j en un paso separado, sin re-ingestar archivos ni interrumpir el servicio.

---

## Arquitectura general

```
Documentos (.md)
      │
      ▼
┌──────────────────────────────┐
│   ingestion/ingest.py        │  Pipeline de ingesta
│                              │
│  1. Parsea frontmatter YAML  │
│  2. Extrae entidades (gratis)│  <- sin LLM, solo regex
│  3. Strip Markdown           │  <- reduce tokens Graphiti
│  4. Chunking por segmentos   │
│  5. Genera embeddings        │  <- OpenAI / Gemini
│  6. Guarda en Postgres       │
│  7. (Opcional) -> Graphiti   │  <- truncado a 6000 chars
└──────────────────────────────┘
         │                │
         ▼                ▼
  ┌────────────┐    ┌───────────┐
  │ PostgreSQL │    │  Neo4j    │
  │ (pgvector) │    │(Graphiti) │
  └────────────┘    └───────────┘
         │                 │
         └───────┬─────────┘
                 ▼
        ┌─────────────────┐
        │  agent/tools.py │  Capa de búsqueda
        │                 │
        │ • vector_search │  <- cosine similarity (top 3)
        │ • graph_search  │  <- relaciones/entidades (top 3)
        │ • hybrid_search │  <- RRF (combina ambas) (top 3)
        └─────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │ poc/content_    │  Generación de contenido
        │ generator.py    │  (emails, reels, historias)
        │                 │  max_tokens por formato
        └─────────────────┘
```

**Stack tecnológico:**
- **Python 3.10+** con `asyncio` / `asyncpg` para I/O no bloqueante
- **PostgreSQL** con extensión `pgvector` para búsqueda vectorial
- **Neo4j** como base de datos del knowledge graph
- **Graphiti** (`graphiti-core`) para extracción automática de entidades y relaciones
- **OpenAI**, **Gemini** u **Ollama** como proveedor de LLM y embeddings (configurable)
- **Streamlit** + **Pyvis** para dashboard interactivo y visualización de grafos

---

## Estrategia de despliegue por fases

### Fase 1 — Vector Only (Lanzamiento productivo)

**Objetivo:** velocidad máxima, costo mínimo.

Solo se usa Postgres/pgvector. No se instala Neo4j, no se llama a Graphiti.

```bash
python -m poc.run_poc --ingest documents_to_index/ --skip-graphiti
```

---

### Fase 1.5 — Metadata Enrichment (sin costo extra)

**Objetivo:** preparar la base de datos para que la migración al grafo sea más barata y precisa.

Durante la ingesta normal, el pipeline extrae automáticamente metadatos estructurados **sin gastar ni un token de LLM**:

- **Personas detectadas:** regex sobre el bloque "Participantes:" o nombres Nombre Apellido en el texto.
- **Empresas y herramientas:** palabras con mayúscula que aparecen ≥2 veces.
- **Segmentos temporales:** timestamps `[MM:SS]` del formato Novotalks, usados como límites de chunk.
- **Citas destacadas:** bloques `> "..."` del markdown.
- **`graphiti_ready_context`:** string pre-formateado con todo lo anterior, listo para Graphiti.

Ejemplo de contexto generado automáticamente:
```
Document: Agustín Linenberg - Ventas y Startups | Category: Podcast |
People: Agustín Linenberg, Wences Casares |
Organizations: Aerolab, Clay, Lemon Wallet |
Topics: Perfil Personal; Emprender por Accidente; Ventas por Relación
```

Frontmatter opcional para enriquecer metadatos:
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

```bash
# Preview: ver qué documentos se procesarían
python -m poc.hydrate_graph --dry-run

# Ejecutar la migración (secuencial, 5s entre episodios)
python -m poc.hydrate_graph

# Solo los primeros 10 (validar costos antes de escalar)
python -m poc.hydrate_graph --limit 10

# Sin pausa entre episodios (si el tier de API lo permite)
python -m poc.hydrate_graph --delay 0

# Re-procesar todos
python -m poc.hydrate_graph --reset-flags
```

---

## Instalación y configuración

### Opción A — Docker (recomendado)

Todo el stack se levanta con un solo comando. Solo necesitás Docker y (opcionalmente) Ollama en el host.

```bash
git clone <repo>
cd poc-graphiti-agent

# 1. Crear .env desde el template
cp .env.example .env
# Editar .env con tus keys/passwords (ver opciones abajo)

# 2. Levantar todo (Postgres + Neo4j + Dashboard)
docker compose up --build -d

# 3. Abrir el dashboard
# http://localhost:8501
```

**Correr ingesta u otros comandos CLI dentro del container:**
```bash
docker compose exec app python -m poc.run_poc --ingest "documents_to_index" --all
docker compose exec app python -m poc.hydrate_graph --limit 5
```

**Conectar a Ollama del host:** El container usa `host.docker.internal` para alcanzar Ollama. Asegurate de que Ollama esté corriendo en el host (`ollama serve`) y que `.env` tenga:
```
OPENAI_BASE_URL=http://host.docker.internal:11434/v1
```

**Parar todo:**
```bash
docker compose down          # Mantiene datos
docker compose down -v       # Borra datos (Postgres + Neo4j)
```

---

### Opción B — Manual (sin Docker para la app)

#### Requisitos
- Python 3.10+
- Docker (para Postgres y Neo4j)
- (Opcional) [Ollama](https://ollama.com/) para modelos locales

#### 1. Clonar e instalar dependencias

```bash
git clone <repo>
cd poc-graphiti-agent
pip install -r requirements.txt
```

#### 2. Levantar Postgres y Neo4j con Docker

```bash
docker compose up postgres neo4j -d
```

#### 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` según el proveedor elegido.

> **Nota:** En setup manual, cambiar los hosts a `localhost`:
> - `NEO4J_URI=neo4j://127.0.0.1:7687`
> - `POSTGRES_HOST=localhost` / `POSTGRES_PORT=5435`
> - `OPENAI_BASE_URL=http://localhost:11434/v1` (si usás Ollama)

**OpenAI (cloud):**
```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
DEFAULT_MODEL=gpt-5-mini
EMBEDDING_MODEL=text-embedding-3-small
```

**Ollama (local, $0 costo):**
```
LLM_PROVIDER=ollama
DEFAULT_MODEL=qwen2.5:3b
EMBEDDING_MODEL=nomic-embed-text
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=adminadmin
POSTGRES_DSN=postgresql://user:password@localhost:5432/graphiti_poc
```

> **Nota Ollama:** Los modelos `qwen2.5:3b` y `nomic-embed-text` se descargan automáticamente si no están instalados. El sistema configura automáticamente `small_model` para evitar que Graphiti intente usar `gpt-4.1-nano` y se pasa un timeout extendido (1800s) al cliente OpenAI para tolerar los tiempos de respuesta de modelos locales.

---

## Cómo correr el proyecto

### Flujo completo (ingesta + búsquedas + generación)

```bash
python -m poc.run_poc --clear-logs --clear-db --ingest "documents_to_index" --all
```

> `--clear-db` ahora limpia **tanto Postgres como Neo4j** (nodos, relaciones e índices).

### Solo ingesta vectorial (sin Graphiti, más rápido y barato)

```bash
python -m poc.run_poc --ingest documents_to_index/ --skip-graphiti
```

### Ingesta limitada (para pruebas rápidas)

```bash
python -m poc.run_poc --ingest "documents_to_index" --max-files 2 --all
```

### Solo búsquedas de prueba

```bash
python -m poc.run_poc --search
```

### Solo generación de contenido

```bash
python -m poc.run_poc --generate
```

### Hidratar Graphiti desde Postgres (Fase 2)

```bash
python -m poc.hydrate_graph --limit 5
```

### Dashboard interactivo

```bash
python -m streamlit run dashboard/app.py
```

El dashboard incluye 7 tabs: Ingestion, Knowledge Base, Search, Generation, Analytics, Proyecciones y **Neo4j Graph** (ver sección 12).

---

## Estructura de archivos explicada

```
poc-graphiti-agent/
├── agent/
│   ├── config.py                 # Variables de entorno (Settings con Pydantic)
│   ├── custom_openai_client.py   # Cliente OpenAI con fixes para gpt-5-mini y retry
│   ├── db_utils.py               # Pool de conexiones Postgres + queries
│   ├── gemini_client.py          # Cliente Gemini para Graphiti
│   ├── graph_utils.py            # Wrapper Graphiti/Neo4j + monkey-patch UUID safety
│   ├── models.py                 # Modelos Pydantic (SearchResult, etc.)
│   └── tools.py                  # Herramientas de búsqueda (vector/graph/hybrid)
├── dashboard/
│   ├── app.py                    # Dashboard Streamlit (7 tabs incluido Neo4j Graph)
│   └── utils.py                  # Utilidades del dashboard
├── ingestion/
│   ├── chunker.py                # RecursiveChunker (chunk_size=800, overlap=100)
│   ├── embedder.py               # EmbeddingGenerator con cache (soporta Ollama)
│   └── ingest.py                 # Pipeline completo de ingesta
├── poc/
│   ├── check_system.py           # Health check pre-vuelo
│   ├── config.py                 # Precios de modelos + defaults Ollama
│   ├── content_generator.py      # Generador de contenido con límites de tokens
│   ├── cost_calculator.py        # Calcula costo USD por operación
│   ├── hydrate_graph.py          # Migración secuencial Postgres -> Neo4j
│   ├── logging_utils.py          # Loggers CSV por tipo de operación
│   ├── prompts/                  # Templates por formato (email, reel, historia)
│   ├── queries.py                # 20 queries de prueba (vector/graph/hybrid)
│   ├── run_poc.py                # Entrypoint principal (--max-files, --clear-db)
│   └── token_tracker.py          # Singleton de tracking de tokens y costos
├── tools/
│   ├── neo4j_diagnostic.py       # Script de diagnóstico Neo4j (conteo, labels, edges)
│   └── neo4j_viewer.py           # Visualizador standalone (Streamlit + Pyvis)
├── documents_to_index/           # Documentos .md a ingestar
├── logs/                         # CSVs de métricas generados automáticamente
├── Dockerfile                    # Build multi-stage (Python 3.13-slim)
├── .dockerignore
├── docker-compose.yml            # Postgres + Neo4j + App (3 servicios)
├── .env.example                  # Template de variables de entorno para Docker
├── requirements.txt
└── README.md
```

---

## Flujo de datos de punta a punta

### Ingesta (`ingest.py`)

1. **Lectura:** carga el archivo `.md` en memoria.
2. **Deduplicación:** calcula SHA256 del contenido; si ya existe en Postgres, saltea.
3. **Frontmatter:** extrae metadatos YAML del bloque `---`.
4. **Extracción heurística (sin LLM):** personas, empresas, citas, segmentos temporales.
5. **Strip de Markdown:** elimina `##`, `**`, `>`, `-`, etc. antes de enviar a Graphiti (ahorra 5-15% de tokens).
6. **Chunking:** divide el texto en chunks de 800 chars con 100 de overlap.
7. **Embedding:** genera vectores en batch (una sola llamada a la API).
8. **Postgres:** guarda documento y chunks con sus embeddings.
9. **Graphiti (opcional):** envía el texto (truncado a 6.000 chars) para extracción de entidades y relaciones.

### Búsqueda (`tools.py`)

- **`vector_search_tool`:** embeddea la query (con cache), busca por cosine similarity en Postgres, retorna top-3.
- **`graph_search_tool`:** busca hechos y relaciones en Neo4j via Graphiti, retorna top-3.
- **`hybrid_search_tool`:** combina vector + full-text con Reciprocal Rank Fusion (RRF), retorna top-3.

### Generación (`content_generator.py`)

Recibe los resultados de búsqueda como contexto, los inyecta en el template del formato solicitado, y llama al LLM con un límite de tokens por formato (email: 300, reel: 250, historia: 500).

---

## Sistema de métricas y costos

Cada operación genera una fila en los logs CSV:

| Log | Contenido |
|-----|-----------|
| `logs/ingesta_log.csv` | Costo por documento ingestado, tokens usados, tiempo |
| `logs/busqueda_log.csv` | Costo por query, tipo de búsqueda, latencia |
| `logs/generacion_log.csv` | Costo por pieza generada, tokens in/out, formato |

---

## Optimizaciones de costo implementadas

Esta sección documenta todos los cambios técnicos realizados para reducir el consumo de tokens y corregir errores que causaban pérdidas de costo.

### Bugs corregidos

#### BUG 1: UnicodeEncodeError en Windows — `custom_openai_client.py`
**Síntoma:** El sistema loggeaba un "Logging error" al arrancar en Windows y el mensaje de inicialización de Graphiti fallaba silenciosamente.

**Causa raíz:** El mensaje de log usaba la flecha unicode `→` (U+2192). La consola de Windows con encoding `cp1252` no puede encodear ese carácter, y el módulo `logging` lanzaba una excepción interna.

**Fix:** Todos los mensajes de log ahora usan únicamente caracteres ASCII (`->`).

---

#### BUG 2: LengthFinishReasonError en todos los episodios — `custom_openai_client.py`
**Síntoma:** 100% de las llamadas a `add_episode()` fallaban con:
```
LengthFinishReasonError: Could not parse response content as the length limit was reached
completion_tokens=2048, reasoning_tokens=2048
```

**Causa raíz:** `gpt-5-mini` es un **modelo de razonamiento** (familia `o1`). Antes de producir output visible, consume *reasoning_tokens* de forma interna. Con el límite heredado de `graphiti-core` (`DEFAULT_MAX_TOKENS = 2048`), el modelo usaba los 2048 tokens **enteros** en razonamiento, dejando 0 tokens para el JSON estructurado que Graphiti necesita parsear.

El log lo confirmaba: `reasoning_tokens=2048` en cada intento fallido.

**Fix:** Para modelos de razonamiento (`gpt-5-*`, `o1-*`), se fuerza `max_completion_tokens = 8192`. El peor caso observado en los logs (prompt ~19.6k tokens) requiere ~4.000-5.000 reasoning tokens + ~400 para el JSON de output. Los tokens no usados no se facturan.

---

#### BUG 3: CancelledError en archivos pendientes — `ingestion/ingest.py`
**Síntoma:** Dos archivos fallaban por BUG 2 y los tres archivos restantes recibían `CancelledError` en lugar de procesarse normalmente.

**Causa raíz:** `ingest_file()` hacía `raise` en su bloque `except`, propagando la excepción hacia el `asyncio.gather()`. Aunque `gather()` usaba `return_exceptions=True`, en Python 3.13 las tareas que estaban *esperando adquirir el semáforo* recibían `CancelledError` al detectar que el semáforo fue liberado por una excepción.

**Fix:** `ingest_file()` ya no hace `re-raise`. Loggea el error con `logger.exception()` y retorna `None`. El `gather()` ve `None` (no `Exception`) y continúa con los archivos restantes sin interrupciones.

---

#### BUG 4: NameError en retries por import faltante — `custom_openai_client.py`
**Síntoma:** Los retries con backoff exponencial ante errores 429 nunca se ejecutaban; el sistema lanzaba `NameError: name 'asyncio' is not defined` en `_make_request_with_retry()`.

**Causa raíz:** `import asyncio` solo estaba dentro del método `setup()` (scope local). Cuando `_make_request_with_retry()` llamaba a `asyncio.sleep(delay)`, el nombre `asyncio` no existía en el scope del módulo.

**Fix:** Se movió `import asyncio` al nivel de módulo (línea 1). Además, se agregó inicialización perezosa del semáforo de concurrencia (`_semaphore`) dentro de `_make_request_with_retry()` para que el cliente funcione correctamente incluso si `setup()` nunca se llama.

---

#### BUG 5: Graphiti solo muestra un episodio — `graph_utils.py` + `hydrate_graph.py`
**Síntoma:** Al consultar episodios después de la hidratación, solo aparecía un documento (ej. "Alex") en lugar de todos los documentos indexados.

**Causa raíz:** El archivo `graph_utils.py` fue reescrito con una clase `GraphManager` (basada en instancias), pero el resto del código (`tools.py`, `ingest.py`, `run_poc.py`, `check_system.py`) importa `GraphClient` (singleton con `@classmethod`). Esto significa que:
1. Los imports fallaban silenciosamente o el sistema usaba una instancia aislada.
2. `add_episode()` no pasaba `group_id`, y cada episodio terminaba en un grupo distinto.
3. La consulta de episodios no usaba `group_ids=None` para recuperar todos los grupos.

**Fix:** Se restauró la clase `GraphClient` singleton compatible con el resto del código, con estas mejoras:
- `add_episode()` ahora acepta y pasa `group_id` (default: `"hybrid_rag_documents"`) para que todos los documentos pertenezcan al mismo grupo.
- Se agregó `get_all_episodes(group_ids=None)` que usa `client.get_episodes()` para recuperar episodios de **todos** los grupos.
- Se agregaron métodos `reset()` y `_build_client()` requeridos por `run_poc.py` y `check_system.py`.
- `hydrate_graph.py` fue actualizado para usar `GraphClient` en lugar de `GraphManager`.

---

#### BUG 7: KeyError en resolve_extracted_edges con LLMs pequeños — `graph_utils.py`
**Síntoma:** La ingesta de ciertos documentos (ej. `lucas.md`) fallaba con:
```
KeyError: '78edfb08-3cab-4fb4-a9fb-5a88af334189'
```
en `graphiti_core/utils/maintenance/edge_operations.py` línea 317.

**Causa raíz:** Modelos pequeños como `qwen2.5:3b` a veces generan edges (relaciones) que referencian UUIDs de entidades que no existen en la lista de entidades extraídas. El código upstream de Graphiti hace un `dict[uuid]` directo sin verificar si el UUID existe, causando un `KeyError` que aborta la ingesta completa del documento.

**Fix:** Se implementó un **monkey-patch** en `agent/graph_utils.py` que intercepta `resolve_extracted_edges` antes de que procese los edges:
1. Construye un set de UUIDs válidos desde la lista de entidades.
2. Filtra los edges, descartando aquellos con `source_node_uuid` o `target_node_uuid` inexistentes.
3. Loggea un `WARNING` por cada edge descartado.
4. Pasa solo los edges válidos a la función original.

El patch se aplica tanto al módulo `edge_operations` como al import directo en `graphiti_core.graphiti` (que usa `from ... import resolve_extracted_edges`). El documento se ingesta correctamente aunque pierde algunos edges que el LLM generó incorrectamente.

---

#### BUG 6: Retries infinitos ante quota agotada — `custom_openai_client.py`, `embedder.py`, `run_poc.py`
**Síntoma:** Cuando la cuenta de OpenAI no tiene créditos, la API responde con 429 y `code: insufficient_quota`. El sistema reintentaba indefinidamente (hasta 5 veces con delays crecientes) sin jamas poder triunfar, y terminaba con un `KeyboardInterrupt` del usuario.

**Causa raíz:** OpenAI usa el mismo código HTTP 429 para dos tipos de error muy distintos: (1) rate limit transitório (se recupera solo) y (2) quota agotada (requiere acción del usuario). El código anterior no diferenciaba entre ellos.

**Fix:**
- `custom_openai_client.py`: En el handler de `RateLimitError`, se verifica `e.code == 'insufficient_quota'` antes de calcular el backoff. Si es quota, se loggea un mensaje `CRITICAL` con el link de billing y se re-lanza inmediatamente sin reintentos.
- `embedder.py`: Mismo chequeo en `generate_embeddings_batch()` y `_embed_one()` para errores de embedding.
- `run_poc.py`: Se separa `_main()` de `main()`. El wrapper `main()` captura cualquier excepción, detecta si es quota (por `e.code` o por contenido del mensaje), muestra un banner `FATAL ERROR` con instrucción clara y sale con `SystemExit(1)` en lugar de crashear con `CancelledError` o `KeyboardInterrupt`.

---

### Optimizaciones de costo

| Módulo | Cambio | Ahorro estimado |
|--------|--------|-----------------|
| `agent/custom_openai_client.py` | `small_model` forzado a `medium_model` (evita `gpt-4.1-nano` con límite TPM 200k) | Elimina rate limits en ingesta |
| `agent/custom_openai_client.py` | Retry con backoff exponencial ante 429 (5 intentos: 10/20/40/80/160s) | Recupera episodios que antes se perdían |
| `agent/graph_utils.py` | Truncado de `episode_body` a **6.000 chars** antes de `add_episode()` | ~60% de tokens en Graphiti |
| `agent/tools.py` | Resultados de búsqueda: **5 → 3** (vector, hybrid, graph) | ~400 tokens de input por query |
| `ingestion/ingest.py` | Strip de sintaxis Markdown antes de Graphiti | 5-15% de tokens por episodio |
| `ingestion/chunker.py` | `chunk_size`: 1000 → **800**, `chunk_overlap`: 200 → **100** | ~50% de tokens duplicados en embedding |
| `ingestion/embedder.py` | Cache LRU de **256 entradas** para queries repetidas | Queries repetidas: $0 y latencia cero |
| `poc/content_generator.py` | `max_tokens` por formato (email: 300, reel: 250, historia: 500) | 50-80% del costo de generación |
| `poc/hydrate_graph.py` | Procesamiento **secuencial** con delay configurable (`--delay 5`) | Elimina rate limits en hidratación |

---

## Criterios de éxito

### GO — Seguir adelante con producción

- Costo de ingesta < $0.10 por documento
- Costo promedio por query < $0.001
- Latencia de búsqueda < 2 segundos
- Proyección mensual (250 docs) < $100

### OPTIMIZE — Ajustar antes de escalar

- Costo por documento: $0.10 - $0.25
- Proyección mensual: $100 - $200

### STOP — Re-evaluar arquitectura

- Costo por documento > $0.25
- Proyección mensual > $200

---

## Preguntas frecuentes

**¿Por qué el chunk_size es 800 y no 1000?**
Chunks más pequeños producen recuperación más precisa (retorna solo la sección relevante, no párrafos enteros). El ahorro en tokens de contexto en generación supera el leve aumento en costos de embedding de ingesta (que ocurre una sola vez).

**¿Por qué el overlap es 100 y no 200?**
El overlap existe para evitar que ideas queden cortadas sin contexto. Pero cada carácter de overlap se embeddea dos veces (en el chunk anterior y en el siguiente). Con overlap=100 sobre chunk_size=800, solo el 12.5% de los tokens se duplican (antes: 20%). La calidad de recuperación no cambia materialmente para textos conversacionales.

**¿Por qué se trunca el texto antes de enviarlo a Graphiti?**
Graphiti realiza ~30 llamadas LLM internas por episodio, y cada una recibe el texto completo como contexto. Las entidades clave de un documento típico siempre están en las primeras 6.000 caracteres. Truncar a ese límite reduce ~60% del costo de Graphiti sin impactar la calidad del grafo.

**¿Por qué `gpt-5-mini` necesita `max_completion_tokens = 8192`?**
`gpt-5-mini` pertenece a la familia de modelos de razonamiento (`o1`). Antes de producir output visible, consume *reasoning tokens* de forma interna. Con el límite por defecto de 2048 tokens, el modelo usa todos los tokens en razonamiento y no le queda espacio para generar el JSON estructurado que Graphiti necesita. Aumentar el límite a 8192 da el espacio necesario; los tokens no usados no se cobran.

**Por que la hidratacion es secuencial y no paralela?**
`add_episode()` dispara internamente ~30 llamadas LLM en paralelo. Si se procesan 2-3 episodios simultáneos, se multiplican las llamadas paralelas por 2-3, agotando el límite de tokens por minuto (TPM) en segundos. El procesamiento secuencial con un delay de 5 segundos entre episodios permite que la ventana de TPM se renueve parcialmente y elimina los errores 429.

---

## 12. Nuevos Componentes — Motor IA Novolabs

Esta sección documenta las 5 nuevas capas funcionales agregadas al proyecto.

### Tarea 1 — Capa de Servicios (`services/`)

Una capa intermedia entre el dashboard/API y la lógica interna. Separa "qué hace el sistema" de "cómo lo hace internamente", facilitando crear una API REST en el futuro sin tocar el dashboard.

| Archivo | Qué hace |
|---|---|
| `services/ingestion_service.py` | Orquesta la ingesta: deduplicación, chunking, embeddings, almacenamiento |
| `services/generation_service.py` | Delega al agente correcto y retorna el output estructurado |
| `services/search_service.py` | Fachada para los 4 modos de búsqueda (vector, grafo, híbrido, híbrido-real) |

### Tarea 2 — Fuentes de Documentos Enchufables (`ingestion/sources/`)

El sistema ahora puede ingestar desde cualquier origen de datos sin modificar el pipeline principal.

| Archivo | Qué hace |
|---|---|
| `ingestion/sources/base.py` | Clase abstracta `DocumentSource` — define el contrato que toda fuente debe cumplir |
| `ingestion/sources/local_file_source.py` | Lee archivos `.md` desde una carpeta local (implementado) |
| `ingestion/sources/google_drive_source.py` | Stub para futura integración con Google Drive (Fase 1) |

**Uso:** `from ingestion.ingest import ingest_from_source` — acepta cualquier `DocumentSource`.

### Tarea 3 — Agentes de Generación Estructurada (`poc/agents/`)

Cada formato de contenido tiene su propio agente con instrucciones específicas (SOP) y validación de calidad. El output no es texto libre — es un objeto JSON con campos definidos (Hook, Script, CTA, etc.).

| Agente | Formato que genera |
|---|---|
| `ReelCTAAgent` | Guion de reel (Instagram/TikTok) con CTA |
| `HistoriaAgent` | Secuencia de 5-7 Stories de Instagram |
| `EmailAgent` | Email de newsletter o outreach |
| `ReelLeadMagnetAgent` | Reel que promociona un recurso gratuito |
| `AdsAgent` | Copy para Meta Ads o Google Ads |

Los archivos de instrucciones (SOPs) están en `config/sops/` y pueden editarse sin tocar código.

**Uso en dashboard:** Tab "Generation" → sección "Agentes Estructurados" → elegir formato → completar campos → botón "Generar con Agente Estructurado".

**Uso en CLI:** `python -m poc.run_poc --generate-structured --formato reel_cta --topic "tu tema"`

### Tarea 4 — Control de Presupuesto (`poc/budget_guard.py`)

Evita sorpresas de facturación al monitorear el gasto mensual acumulado y cambiar automáticamente al modelo más barato cuando se supera el 90% del límite.

| Variable de entorno (`.env`) | Valor por defecto | Qué hace |
|---|---|---|
| `MONTHLY_BUDGET_USD` | `10.0` | Límite mensual en USD. `0` = desactivado |
| `FALLBACK_MODEL` | `gpt-4o-mini` | Modelo barato que se activa al llegar al 90% |
| `BUDGET_TRACKING_FILE` | `logs/monthly_budget.json` | Donde se guarda el gasto acumulado |

**Alertas automáticas:** WARNING al 70%, CRITICAL al 90% (con cambio de modelo).

El presupuesto se muestra en el dashboard (tab Analytics → sección "Estado del Presupuesto").

### Tarea 5 — Motor de Búsqueda Híbrido Real (`agent/retrieval_engine.py`)

La búsqueda híbrida existente combina vector y FTS dentro de Postgres solamente. `RetrievalEngine` agrega un tercer paso: usa Neo4j para identificar qué documentos son conceptualmente relevantes, y luego va a Postgres a buscar el texto literal de esos documentos.

```
Query del usuario
      │
      ▼
 Neo4j / Graphiti   → identifica "qué documentos mencionan este concepto"
      │
      ▼
  PostgreSQL       → trae los chunks literales de esos documentos
      │
      ▼
 Resultado enriquecido (contexto conceptual + texto literal)
```

**Cuándo usar `hybrid_real`:** Cuando la query es relacional ("qué dijo X sobre Y", "qué documentos hablan de Z"). Para queries semánticas directas, `hybrid` sigue siendo más rápido.

**Fallback automático:** Si Neo4j no retorna resultados, el motor cae automáticamente a búsqueda vectorial.

---

## 13. Soporte Ollama (Modelos Locales)

El sistema puede correr 100% local usando [Ollama](https://ollama.com/), eliminando costos de API. Para activarlo:

1. Instalar Ollama y descargar los modelos:
   ```bash
   ollama pull qwen2.5:3b
   ollama pull nomic-embed-text
   ```

2. Configurar `.env` con `LLM_PROVIDER=ollama` (ver sección Instalación).

### Archivos modificados para Ollama

| Archivo | Cambio |
|---|---|
| `poc/config.py` | Validador `_resolve_gemini_defaults` extendido para detectar `ollama` y setear defaults (`qwen2.5:3b`, `nomic-embed-text`, `http://localhost:11434/v1`). Precios de modelos Ollama agregados como `$0.0`. |
| `agent/graph_utils.py` | Branch `elif provider == "ollama"` en `get_client()` que configura `OpenAIClient` y `OpenAIEmbedder` con la URL de Ollama. Se pasa `small_model=settings.DEFAULT_MODEL` a `LLMConfig` para evitar que Graphiti use `gpt-4.1-nano`. Timeout del cliente extendido a 1800s. |
| `ingestion/embedder.py` | Soporte Ollama en `Embedder.__init__()` configurando `AsyncOpenAI` con `base_url` de Ollama. |
| `agent/db_utils.py` | Detección de dimensión de embedding: 768 para Ollama/Gemini (nomic-embed-text), 1536 para OpenAI. Auto-recreación del schema si las dimensiones no coinciden. |
| `agent/custom_openai_client.py` | `base_url` configurable desde `OPENAI_BASE_URL` env var para redirigir a Ollama. |

### Limitaciones conocidas con Ollama

- **Velocidad:** Modelos locales son ~10-50x más lentos que APIs cloud. Una ingesta de 5 documentos puede tomar ~15-20 minutos.
- **Calidad de edges:** `qwen2.5:3b` genera UUIDs inconsistentes en ~10-20% de los documentos. El monkey-patch (BUG 7) mitiga esto saltando edges rotos.
- **Max tokens:** El modelo puede exceder el límite de `max_tokens=16384`, causando retries. Esto es normal y el sistema reintenta automáticamente.

---

## 14. Neo4j Graph Explorer (Dashboard Tab)

El tab **🔵 Neo4j Graph** en el dashboard provee una interfaz completa para explorar el knowledge graph:

### Métricas
- Conteo de nodos, relaciones, episodios y entidades.

### Sub-tabs

| Sub-tab | Qué muestra |
|---|---|
| **Interactive Graph** | Grafo interactivo con [Pyvis](https://pyvis.readthedocs.io/). Nodos coloreados por label (Entity=azul, Episodic=naranja, Community=verde). Filtro por label, slider de max nodos, toggle de physics. |
| **Episodes** | Lista de documentos ingresados con metadata (nombre, fecha de creación, group_id, source_description). |
| **Details** | Breakdown de labels de nodos y tipos de relación con conteos. |
| **Cypher Query** | Permite ejecutar cualquier query Cypher directo contra Neo4j. Resultados en tabla interactiva. |

### Herramientas de diagnóstico (CLI)

```bash
# Diagnóstico completo (nodos, labels, episodios, entidades, edges)
python tools/neo4j_diagnostic.py

# Quick check (conteos básicos)
python tools/_quick_check.py
```