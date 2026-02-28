# Novolabs AI Engine

Sistema de generación automatizada de contenido semanal para Novolabs.
Ingesta transcripciones → genera reels, historias, emails y ads → publica en Notion.

**Versión:** 2.0 (Fase 1 - Simplificada)  
**Stack:** FastAPI + PostgreSQL + pgvector + n8n  
**Estado:** En desarrollo activo

---

## Arquitectura simplificada (v2.0)

La arquitectura v2.0 incorpora feedback de revisión técnica externa. Los cambios principales respecto a v1.0:

**Neo4j es ahora opcional.** En Fase 1 el sistema corre 100% sobre PostgreSQL con metadata enriquecida. Neo4j se activa en Fase 2 cuando el volumen de documentos justifique traversals de grafo complejos. Esto elimina el problema más complejo del diseño anterior (entity resolution) y reduce el stack de 3 a 2 servicios core.

**QA Gate programático.** Las validaciones de calidad son por defecto programáticas (longitud, presencia de CTA, detección de idioma). El LLM solo valida en muestras aleatorias del 10%, no en cada pieza. Esto reduce el costo de QA aproximadamente un 90%.

**Sin frameworks de agentes.** Los subagentes son clases Python con `generate()`, `_build_prompt()` y `_parse_response()`. Sin Pydantic AI ni LangGraph en Fase 1. LangGraph queda eliminado del roadmap hasta que haya un caso de uso concreto.

**Metadata semántica en Postgres.** En vez de depender de Neo4j para clasificar contenido, cada chunk tiene metadata JSONB enriquecida con `source_type`, `topics`, `domain`, `content_level`, `emotion`, `used_count` y `last_used_at`. Esto permite filtros avanzados y diversity tracking sin infraestructura adicional.

### Flujo semanal

```
Lunes–Jueves   Ingesta de transcripciones
               n8n detecta archivo en Google Drive → POST /ingest
               TaxonomyManager clasifica chunk → metadata enriquecida en Postgres

Viernes        Equipo define qué generar en "Weekly Rules" de Notion

Domingo 23:00  n8n dispara → POST /generate/weekly
               Orquestador lee Weekly Rules → busca chunks con diversidad
               Subagentes generan piezas → QA Gate programático
               Piezas aprobadas → Notion (estado: Propuesta)
               Telegram notifica resultados

Lunes          Equipo revisa, aprueba y publica desde Notion
```

### Stack

| Componente | Rol | Fase |
|---|---|---|
| FastAPI | API HTTP para n8n | Fase 1 |
| PostgreSQL + pgvector | Almacenamiento principal, embeddings, metadata | Fase 1 |
| n8n | Triggers automáticos (Google Drive, cron semanal) | Fase 1 |
| Notion API | Output final, SOPs, Weekly Rules, calificaciones | Fase 1 |
| Telegram Bot | Alertas de ingesta, errores, budget | Fase 1 |
| Neo4j + Graphiti | Grafo de conocimiento (OPCIONAL) | Fase 2+ |

---

## Estructura del proyecto

```
novolabs-ai-engine/
│
├── api/                        # FastAPI
│   ├── main.py                 # Entry point, lifespan, routers
│   ├── routes/
│   │   ├── health.py           # GET /health
│   │   ├── ingest.py           # POST /ingest
│   │   └── generate.py         # POST /generate/weekly
│   └── models/
│       ├── ingest.py           # IngestRequest, IngestResponse
│       └── generate.py         # GenerateRequest, GenerateResponse
│
├── agents/                     # Subagentes de generación
│   ├── base_agent.py           # Clase base con QA Gate programático
│   ├── reel_cta_agent.py       # Genera Reels CTA
│   ├── reel_lm_agent.py        # Genera Reels Lead Magnet
│   ├── historia_agent.py       # Genera Historias
│   ├── email_agent.py          # Genera Emails
│   └── ads_agent.py            # Genera Anuncios (Fase 1)
│
├── orchestrator/               # Orquestador del flujo semanal
│   ├── base.py                 # Clase abstracta JobType
│   ├── main.py                 # Main Orchestrator
│   └── weekly_job.py           # WeeklyContentJob
│
├── ingestion/                  # Pipeline de ingesta
│   ├── ingest.py               # Coordinador de ingesta
│   ├── taxonomy.py             # TaxonomyManager (clasificación sin LLM)
│   └── sources/                # Adaptadores de fuentes
│
├── storage/                    # Clientes de storage
│   ├── notion_client.py        # Notion API (leer SOPs, publicar piezas)
│   └── db_pool.py              # Connection pool Postgres
│
├── agent/                      # Utilidades de bajo nivel (del POC, refactorizar gradualmente)
│   ├── config.py               # Settings centralizados (ENABLE_GRAPH, etc.)
│   ├── custom_openai_client.py # Cliente OpenAI con rate limit handling
│   ├── db_utils.py             # Helpers de base de datos
│   └── tools.py                # Búsqueda vectorial con diversity
│
├── monitoring/                 # Observabilidad
│   └── telegram.py             # Notificaciones Telegram
│
├── poc/                        # Scripts del POC original (NO producción)
│   ├── budget_guard.py         # Budget Guard (✅ completado)
│   └── ...                     # Scripts de inspección y debug
│
├── sql/
│   └── schema.sql              # Schema Postgres v2.0 con metadata enriquecida
│
├── config/
│   ├── taxonomy.json           # Keywords de clasificación (TODO)
│   └── job_schedule.json       # Configuración del cron (TODO)
│
├── tests/
│   ├── test_taxonomy.py        # Tests del TaxonomyManager
│   ├── test_ingest.py          # Tests del pipeline de ingesta
│   └── test_agents.py          # Tests de generación
│
├── docker-compose.yml          # PostgreSQL + API (Neo4j en perfil opcional)
├── Dockerfile                  
├── requirements.txt            
├── .env.example                
└── README.md
```

---

## Setup inicial

### Prerequisitos

- Docker y Docker Compose
- Python 3.11+
- Cuenta OpenAI con API key

### 1. Variables de entorno

```bash
cp .env.example .env
# Editar .env con tus valores reales
```

Campos obligatorios en `.env`:

```bash
OPENAI_API_KEY=sk-...
POSTGRES_PASSWORD=tu_password_seguro
MONTHLY_BUDGET_USD=50       # Límite mensual en USD
```

Campos opcionales para Fase 1 (completar cuando corresponda):

```bash
NOTION_TOKEN=               # Necesario para Módulo 1.2
TELEGRAM_BOT_TOKEN=         # Necesario para Módulo 1.5
TELEGRAM_CHAT_ID=
```

### 2. Levantar servicios

```bash
# Fase 1: solo PostgreSQL + API
docker compose up -d

# Verificar salud
curl http://localhost:8000/health
```

Para activar Neo4j (solo Fase 2+):

```bash
ENABLE_GRAPH=true docker compose --profile graph up -d
```

### 3. Inicializar base de datos

El schema se aplica automáticamente al iniciar PostgreSQL si está en `sql/schema.sql`. Para aplicar manualmente:

```bash
docker exec -i novolabs_postgres psql -U novolabs -d novolabs < sql/schema.sql
```

---

## Endpoints

### GET /health

Verifica el estado del sistema. Usado por n8n antes de enviar archivos.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "postgres": "ok",
  "neo4j": "disabled",
  "budget_used_pct": 12.5,
  "budget_remaining_usd": 43.75
}
```

### POST /ingest

Ingesta un documento. n8n lo llama cuando detecta un archivo nuevo en Google Drive.

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "sesion_14_validacion.md",
    "content": "# Sesión 14\n...",
    "source_type": "sesion_grupal",
    "skip_graphiti": true,
    "extra": {"edition": 14}
  }'
```

```json
{
  "doc_id": "uuid",
  "chunks_count": 12,
  "cost_usd": 0.002,
  "taxonomy": {
    "domain": "ventas",
    "topics": ["validacion", "objeciones"],
    "content_level": 2
  }
}
```

### POST /generate/weekly

Dispara la generación semanal. n8n lo llama el domingo a las 23:00.

```bash
curl -X POST http://localhost:8000/generate/weekly \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

```json
{
  "run_id": "uuid",
  "pieces_generated": 48,
  "pieces_failed": 2,
  "pieces_qa_passed": 45,
  "cost_usd": 8.40,
  "notion_urls": ["https://notion.so/..."]
}
```

---

## Metadata de chunks

Cada chunk almacenado en Postgres tiene metadata JSONB enriquecida, clasificada automáticamente por `TaxonomyManager` en el momento de la ingesta (sin LLM):

```json
{
  "source_type":    "sesion_grupal",
  "speaker_role":   "alumno",
  "topics":         ["validacion", "objeciones", "pricing"],
  "content_level":  2,
  "emotion":        "frustracion",
  "domain":         "ventas",
  "edition":        14,
  "alumno_id":      "juan-garcia",
  "fecha":          "2026-02-15",
  "used_count":     0,
  "last_used_at":   null,
  "is_deleted":     false
}
```

Esta metadata permite:
- Filtros avanzados en búsqueda (`domain=ventas`, `topics=objeciones`)
- Diversity tracking sin tabla extra (`used_count`, `last_used_at`)
- Analytics de fuentes más usadas y mejor calificadas

---

## QA Gate

El sistema valida cada pieza generada en dos capas:

**Capa 1 - Programática (siempre, gratis):**

- CTA presente y con longitud mínima
- Detección de inglés por heurística de keywords
- Campos obligatorios presentes según el formato
- Longitud dentro de rangos esperados (hook, script, cuerpo)

**Capa 2 - LLM (10% de piezas, muestreo aleatorio):**

- Calidad de storytelling
- Tono y voz coherentes con Novolabs
- Solo se ejecuta si la pieza ya pasó la Capa 1

**Retry automático:** Si una pieza falla QA, se regenera una vez. Si vuelve a fallar, se marca como `QA_Failed` y continúa con la siguiente pieza (no bloquea el run).

---

## Diversity Selector

El sistema evita repetir fuentes usando los campos `used_count` y `last_used_at` en la metadata del chunk:

- Los chunks usados en los últimos 30 días reciben una penalización del 30% en su score de búsqueda
- El score final es: `base_score × diversity_factor` (donde `diversity_factor = 0.70` si fue usado recientemente, `1.0` si no)
- Después de usar un chunk, `mark_chunk_used()` actualiza su metadata en Postgres

No hay tabla `used_sources` separada. Todo vive en la metadata del chunk.

---

## Budget Guard

El sistema tiene protección de presupuesto desde el primer run:

| Umbral | Acción |
|---|---|
| 70% del budget | Alerta Telegram |
| 90% del budget | Alerta Telegram + cambio automático a `FALLBACK_MODEL` |
| 100% del budget | Generación bloqueada hasta el mes siguiente |

Configurar en `.env`:

```bash
MONTHLY_BUDGET_USD=50
FALLBACK_MODEL=gpt-4.1-mini
```

---

## Costos estimados (100 piezas/semana)

| Operación | Llamadas | Costo estimado |
|---|---|---|
| Search Intent Generator (5 ángulos × 4 tópicos) | ~20 | ~$0.40 |
| Generación de piezas | ~100 | ~$6.00 |
| QA LLM (10% de piezas) | ~10 | ~$0.30 |
| Embeddings de ingesta (semanal) | variable | ~$0.20 |
| **Total semanal estimado** | | **~$7–10** |

Gemini Flash 2.0 es una alternativa más barata si el costo supera el target de $10/semana.

---

## Roadmap

### Fase 1 (Semanas 1–6): MVP funcional ← _Estamos aquí_

- [x] Budget Guard con alertas y fallback automático
- [ ] FastAPI: `/health`, `/ingest`, `/generate/weekly`
- [ ] Notion Integration: leer Weekly Rules y SOPs, publicar piezas
- [ ] Orquestador + WeeklyContentJob
- [ ] Subagentes con output JSON estructurado + QA Gate programático
- [ ] Telegram Bot: alertas de ingesta y resultados
- [ ] n8n: webhook Google Drive + cron dominical
- [ ] TaxonomyManager: clasificación en ingesta sin LLM

**Entregable:** 50–70 piezas/semana automáticas en Notion

### Fase 2 (Semanas 8–12): Calidad y diversidad

- [ ] Activar Neo4j como enriquecedor de búsqueda (ENABLE_GRAPH=true)
- [ ] Diversity tracking histórico con lookback de 30 días
- [ ] QA Gate avanzado: similaridad semántica entre piezas del mismo run
- [ ] SOPs de Notion integrados en prompts de generación

**Entregable:** 100 piezas/semana, >80% aprobación, >85% diversidad

### Fase 3 (Semanas 12–16): Inteligencia

- [ ] Feedback Loop: leer calificaciones de Notion, ajustar prompts
- [ ] MasterclassJob: nuevo Job Type
- [ ] Trending topics desde Neo4j

**Entregable:** Sistema semi-autónomo que sugiere tópicos

---

## Desarrollo

### Tests

```bash
# Test del TaxonomyManager
python -m pytest tests/test_taxonomy.py -v

# Test del pipeline de ingesta (requiere Postgres)
python -m pytest tests/test_ingest.py -v

# Test de generación (requiere OpenAI key + Postgres)
python -m pytest tests/test_agents.py -v
```

### Convenciones

- Los agentes devuelven `ContentPiece`, nunca dicts crudos
- La búsqueda vectorial siempre pasa por `vector_search_with_diversity()`, no directamente por SQL
- El QA Gate programático en `BaseAgent._validate_programmatic()` es la única barrera obligatoria
- `mark_chunk_used()` se llama siempre después de usar un chunk para generar, aunque la pieza falle QA
- Neo4j solo se instancia si `settings.enable_graph is True`

### Variables de entorno en desarrollo

Para desarrollo local sin Docker:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PASSWORD=tu_password
export OPENAI_API_KEY=sk-...
export ENABLE_GRAPH=false
export MONTHLY_BUDGET_USD=10   # límite bajo para desarrollo
```

---

## Por qué esta arquitectura

**¿Por qué Postgres y no Neo4j en Fase 1?**

El problema central del sistema es: *"dado un tópico, dame chunks relevantes"*. Eso es búsqueda vectorial con filtros, no traversal de grafos. Con la metadata enriquecida (`topics`, `domain`, `emotion`, `content_level`) y los índices GIN sobre JSONB, Postgres resuelve ese problema completamente para el volumen actual (miles de documentos). Neo4j suma complejidad operacional, entity resolution como riesgo activo, y un componente adicional en el stack sin beneficio claro en esta etapa.

**¿Cuándo activar Neo4j?**

Cuando el sistema tenga decenas de miles de documentos y sea necesario responder preguntas como: *"¿qué conceptos están más relacionados con el miedo al rechazo en ventas B2B según las últimas 3 ediciones?"*. Ese tipo de traversal justifica el grafo. En Fase 1, no.

**¿Por qué no Pydantic AI ni LangGraph?**

Los agentes actuales son clases Python con `generate()`. Agregar un framework de agentes encima agrega abstracción sin reducir código. LangGraph en particular resuelve routing dinámico entre agentes, algo que el flujo actual (lineal: buscar → generar → validar → publicar) no necesita.