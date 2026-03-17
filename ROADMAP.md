# Novolabs AI Engine — Roadmap MVP

> **Objetivo:** Sistema de generación de contenido semanal automatizado, listo para vender como servicio gestionado a empresas.
> **Estado:** Base técnica completa. Falta integración end-to-end y herramientas de onboarding.
> **Tiempo estimado al MVP vendible:** ~14 semanas

---

## Estado actual

| Componente | Estado | Detalle |
|---|---|---|
| PostgreSQL + pgvector + schema | ✅ Completo | Schema v3.0 con metadata enriquecida |
| Multi-provider LLM (.env) | ✅ Completo | OpenAI / Ollama / Gemini intercambiables |
| Budget Guard + alertas | ✅ Completo | Alertas 70%/90%, fallback automático |
| TaxonomyManager + entidades | ✅ Completo | Keywords + extracción LLM estilo LightRAG |
| Hybrid search + diversity + RRF | ✅ Completo | Búsqueda de 3 capas |
| Docker compose con perfiles | ✅ Completo | local / graph / producción |
| Streamlit dashboard analíticas | ✅ Completo | Búsqueda, ingesta, analíticas, proyecciones |
| Streamlit dashboard configuración | ✅ Completo | Tab de configuración para `.env` y credenciales |
| FastAPI endpoints | ✅ Completo | Endpoints base implementados |
| Orquestador + WeeklyContentJob | ✅ Completo | Weekly Content Job reestructurado |
| Agents refactoring a JSON | ✅ Completo | Output robusto en JSON programático |
| Notion integration | ⏳ En proceso | Schemas parseados, falta conexión completa |
| n8n workflows | ❌ Falta | Sin esto todo es manual |
| Telegram Bot | ❌ Falta | Sin esto no hay visibilidad de runs |
| Flujo de aprobación Notion | ❌ Falta | Sin esto el cliente no puede revisar |
| Multi-tenant (organization_id) | ❌ Falta | Necesario para 2+ clientes |
| Feedback Loop | ❌ Falta | Fase 3, necesita datos reales primero |

---

## Bloqueador crítico

> Sin FastAPI no hay automatización externa. Sin Notion no hay output visible para el cliente.
> Estas dos cosas son el cuello de botella de todo lo demás.
> **Nada de lo que viene después tiene valor si esto no está.**

---

## Fase 1 — Motor funcional end-to-end
**Semanas 1–5 · Objetivo: primer run real en Notion**

### 1.1 FastAPI: /health, /ingest, /generate/weekly `CRÍTICO` `3d`

Entry point para n8n. Sin esto nada puede invocarse externamente.

**Archivos a crear:**
```
api/
├── __init__.py
├── main.py                  ← FastAPI app con lifespan
├── routes/
│   ├── __init__.py
│   ├── health.py            ← GET /health
│   ├── ingest.py            ← POST /ingest
│   └── generate.py          ← POST /generate/weekly
└── models/
    ├── __init__.py
    ├── ingest.py            ← IngestRequest, IngestResponse
    └── generate.py          ← GenerateRequest, GenerateResponse
```

**Endpoint GET /health:**
```json
{
  "status": "ok",
  "postgres": "ok",
  "neo4j": "disabled",
  "llm_provider": "openai",
  "budget": {
    "status": "ok",
    "spent_usd": 8.40,
    "budget_usd": 50.0,
    "used_pct": 16.8
  }
}
```

**Endpoint POST /ingest:**
```json
// Request
{
  "filename": "sesion_14_validacion.md",
  "content": "# Sesión 14\n...",
  "source_type": "sesion_grupal",
  "skip_graphiti": true,
  "extra": { "edition": 14 }
}
// Response
{
  "doc_id": "uuid",
  "chunks_count": 12,
  "entities_extracted": 47,
  "cost_usd": 0.003,
  "skipped": false
}
```

**Endpoint POST /generate/weekly:**
```json
// Request
{ "dry_run": false, "organization_id": "novolabs" }
// Response
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

### 1.2 Notion client: Weekly Rules + SOPs + publicar piezas `CRÍTICO` `3d`

Sin esto el output no llega al equipo.

**Archivos a crear:**
```
storage/
└── notion_client.py         ← NotionClient con todos los métodos
```

**Métodos requeridos:**
- `get_weekly_rules()` → lista de `{formato, cantidad, topico}`
- `get_sop(formato)` → texto del SOP correspondiente
- `publish_piece(content_piece)` → inserta en DB correcta, estado "Propuesta"
- `update_piece_status(page_id, status)` → Propuesta / Aprobada / Rechazada
- `create_weekly_run(run_id, date)` → log en DB Weekly Runs

**Rate limiting:** Notion tiene límite de 3 req/seg. Usar delay de 350ms entre inserts.

**Bases de datos Notion necesarias:**
| DB | Propósito | Propiedades clave |
|---|---|---|
| Weekly Rules | Configura qué generar cada semana | Formato, Cantidad, Tópico, Activo |
| SOPs | Instrucciones por formato | Formato, Contenido |
| Reels | Output de reels generados | Hook, Script, CTA, Rating, Estado |
| Historias | Output de historias | Slides, CTA, Rating, Estado |
| Emails | Output de emails | Asunto, Cuerpo, CTA, Rating, Estado |
| Ads | Output de anuncios | Headlines, Copy, CTA, Rating, Estado |
| Weekly Runs | Log de ejecuciones | Fecha, Piezas, Costo, Estado |

---

### 1.3 Orquestador + WeeklyContentJob `CRÍTICO` `4d`

Conecta todo: lee Notion → busca → genera → valida → publica.

**Archivos a crear:**
```
orchestrator/
├── __init__.py
├── base.py                  ← Clase abstracta JobType
├── main.py                  ← MainOrchestrator
└── weekly_job.py            ← WeeklyContentJob
```

**Flujo del WeeklyContentJob:**
```
1. Leer Weekly Rules desde Notion
2. Para cada regla {formato, topico, cantidad}:
   a. Search Intent Generator: expandir tópico en 5 ángulos
   b. Para cada ángulo:
      - hybrid_search_with_entities() → candidatos
      - Diversity check: excluir chunks usados esa semana
      - Seleccionar top chunk
   c. Para cada chunk seleccionado:
      - get_agent(formato).generate(AgentInput)
      - QA Gate programático
      - Si pasa: publish_piece() en Notion
      - Siempre: mark_chunk_used()
3. Guardar WeeklyRun en Postgres y Notion
4. Notificar por Telegram
```

**Clase base JobType:**
```python
class JobType(ABC):
    @abstractmethod
    def get_requirements(self) -> dict: ...     # qué formatos y cantidades
    @abstractmethod
    def generate_search_intents(self, topic: str) -> list[str]: ...
    @abstractmethod
    def get_subagents(self) -> list[str]: ...   # qué agentes usar
```

---

### 1.4 Refactorizar agentes a output JSON estructurado `CRÍTICO` `3d`

Los agentes actuales producen texto libre. Necesitan producir JSON por formato.

**Archivos a modificar/crear:**
```
poc/agents/
├── base_agent.py            ← Ya actualizado (QA programático)
├── reel_cta_agent.py        ← Output: {hook, script, cta, sugerencias_grabacion, copy}
├── historia_agent.py        ← Output: {tipo, slides:[{texto, visual}], cta_final}
├── email_agent.py           ← Output: {asunto, preheader, cuerpo, cta, ps}
├── ads_agent.py             ← Output: {headlines[3], descripciones[2], copy, cta, visual}
└── reel_lead_magnet_agent.py ← Output: {hook, problema, presentacion_lm, cta}
```

**SOPs en prompts:** cada agente debe recibir el SOP de Notion y usarlo en el system prompt.

---

### 1.5 n8n: webhook Google Drive + cron dominical `CRÍTICO` `2d`

Trigger automático de ingesta y generación semanal.

**Workflows a crear (exportar como JSON):**
1. `novolabs_ingesta_drive.json` — detecta archivo nuevo en Drive → limpia transcripción → POST /ingest
2. `novolabs_generacion_semanal.json` — cron domingo 23:00 → GET /health → POST /generate/weekly

**Variables de entorno en n8n:**
- `NOVOLABS_API_URL` = http://tu-servidor:8000
- `OPENAI_API_KEY` (para preprocesamiento de transcripciones)
- `GOOGLE_DRIVE_FOLDER_ID`

---

### 1.6 Telegram Bot: alertas de run y errores `ALTO` `1d`

**Archivos a crear:**
```
monitoring/
└── telegram.py              ← TelegramNotifier
```

**Mensajes a implementar:**
- `notify_ingestion(filename, chunks, cost)` → al ingestar un doc
- `notify_weekly_results(run_id, generated, approved, cost)` → lunes AM
- `notify_error(error, context)` → cuando falla algo crítico
- `notify_budget_alert(pct, spent, budget)` → al 70% y 90%

---

### 1.7 Diversidad cross-formato en el mismo run `ALTO` `1d`

Si un chunk se usó para Reel, no usarlo para Email esa misma semana.

**Implementación:** el orquestador mantiene un `set[str]` de `chunk_ids` ya usados en el run actual y los pasa como `exclude_chunk_ids` en cada llamada a `hybrid_search_with_entities()`.

---

## Fase 2 — Onboarding y primer cliente
**Semanas 6–8 · Objetivo: cliente real pagando**

Esta fase es la que te permite cobrar. Sin herramientas de onboarding no podés escalar la configuración.

### 2.1 Plantilla Notion lista para duplicar `CRÍTICO` `2d`

El cliente duplica la plantilla y tiene todas las DBs preconfiguradas. Solo necesita conectar su integración de Notion y dar acceso al token.

**Checklist de la plantilla:**
- [ ] DB Weekly Rules con ejemplos de configuración
- [ ] DB SOPs con templates para Reel CTA, Historia, Email, Ads
- [ ] DB Reels con todas las propiedades y vistas configuradas
- [ ] DB Historias
- [ ] DB Emails
- [ ] DB Ads
- [ ] DB Weekly Runs con vista de historial
- [ ] Página de instrucciones "Cómo usar este sistema"

---

### 2.2 Script de validación de onboarding `CRÍTICO` `1d`

Antes del primer run, verificar que todo esté bien configurado.

```bash
python scripts/validate_setup.py
```

**Checks:**
- [ ] Conexión a Postgres (SELECT 1)
- [ ] Conexión a LLM (llamada de prueba)
- [ ] Conexión a Notion (listar DBs)
- [ ] Bases de datos Notion existen con las propiedades correctas
- [ ] Al menos 1 documento ingestado en Postgres
- [ ] Al menos 1 Weekly Rule configurada
- [ ] Budget Guard configurado con límite razonable
- [ ] n8n accesible (GET /health de n8n)

**Output esperado:**
```
✅ Postgres: conectado (12 documentos, 847 chunks)
✅ OpenAI: gpt-4.1-mini disponible
✅ Notion: 7 bases de datos encontradas
✅ Weekly Rules: 4 reglas activas (reel_cta×2, historia×1, email×1)
⚠️  Budget: MONTHLY_BUDGET_USD no configurado, usando default $50
✅ Todo listo para el primer run
```

---

### 2.3 Flujo de aprobación en Notion `CRÍTICO` `2d`

El cliente aprueba/rechaza piezas sin salir de Notion.

**Implementación:**
1. Cada pieza publicada tiene propiedad `Estado`: Propuesta / Aprobada / Rechazada / Regenerar
2. n8n monitorea cambios en Estado cada hora
3. Si Estado = "Regenerar" → llama a `POST /regenerate/{piece_id}`
4. Nuevo endpoint `POST /regenerate/{piece_id}` → regenera la pieza con el mismo chunk pero diferente temperatura

---

### 2.4 Guía de setup no técnica `ALTO` `1d`

Documento para entregar al cliente. Sin jerga técnica.

**Contenido:**
1. Qué accesos necesitás dar (Notion, Google Drive)
2. Cómo duplicar la plantilla de Notion
3. Cómo subir una transcripción a Google Drive
4. Qué hace el sistema cada semana (flujo simplificado)
5. Cómo calificar el contenido generado
6. Qué hacer si algo falla (contacto de soporte)

---

### 2.5 Modo demo con datos sintéticos `ALTO` `1d`

Para reuniones de venta sin mostrar datos reales de otros clientes.

**Implementación:**
```bash
python scripts/load_demo_data.py  # carga 5 transcripciones ficticias
python scripts/run_demo.py        # genera 10 piezas demo
```

**Dataset demo:** 5 transcripciones ficticias de sesiones de ventas B2B con terminología genérica. Genera reels, historias y emails de ejemplo.

---

### 2.6 Reporte semanal automático `ALTO` `1d`

Lunes AM el cliente recibe un resumen del run del domingo.

**Formato Telegram/email:**
```
📊 Run semanal Novolabs — 15 mar 2026

✅ 48 piezas generadas
👍 45 aprobadas por QA (93.7%)
⏳ 45 piezas esperando tu revisión en Notion

📁 Distribución:
  • Reels CTA: 16
  • Historias: 12
  • Emails: 10
  • Ads: 10

💰 Costo total: $8.40
🔤 Palabras generadas: ~24,000

🔗 Ver en Notion → [link al Weekly Run]
```

---

## Fase 3 — Retención y aprendizaje
**Semanas 9–12 · Objetivo: cliente que no se va**

> Implementar esta fase **después de tener al menos 2 clientes reales** con datos de calificación. Sin datos históricos, estas features no tienen valor.

### 3.1 Sincronización de calificaciones desde Notion `ALTO` `2d`

**Flujo:**
1. Script semanal lee ratings 1-5 de cada pieza en Notion
2. Almacena en tabla `feedback` de Postgres
3. Calcula score promedio por formato, tópico y fuente
4. Identifica patrones: qué chunks generan las piezas mejor calificadas

**Query de análisis:**
```sql
SELECT
  c.metadata->>'source_type' AS fuente,
  gc.content_type AS formato,
  AVG(f.rating) AS score_promedio,
  COUNT(*) AS total_piezas
FROM feedback f
JOIN generated_content gc ON f.generated_content_id = gc.id
JOIN chunks c ON gc.chunk_id = c.id
GROUP BY fuente, formato
ORDER BY score_promedio DESC;
```

---

### 3.2 Sugerencias de ajuste de prompt (con aprobación humana) `ALTO` `3d`

> **Importante:** NO implementar ajuste automático. El sistema propone, el humano aprueba.

**Flujo:**
1. Detectar piezas con rating ≤ 2 en las últimas 4 semanas
2. Para cada formato con score promedio < 3.0, enviar a análisis LLM:
   - "Estas piezas de tipo EMAIL tuvieron rating bajo: [ejemplos]. ¿Qué instrucción de 'no hacer X' agregarías al prompt?"
3. LLM genera sugerencia de ajuste
4. Notificar en Telegram con la sugerencia + botón de aprobar
5. Si se aprueba: agregar a `prompt_adjustments` table → se incluye en próximo run

---

### 3.3 Multi-tenant básico (organization_id) `ALTO` `2d`

Aislamiento de datos por cliente. Sin auth compleja: modelo agencia donde vos manejás todo.

**Archivos a modificar:**
```sql
-- Agregar a tablas existentes
ALTER TABLE documents ADD COLUMN organization_id TEXT DEFAULT 'default';
ALTER TABLE chunks ADD COLUMN organization_id TEXT DEFAULT 'default';
ALTER TABLE generated_content ADD COLUMN organization_id TEXT DEFAULT 'default';
ALTER TABLE weekly_runs ADD COLUMN organization_id TEXT DEFAULT 'default';

-- Índices
CREATE INDEX idx_documents_org ON documents(organization_id);
CREATE INDEX idx_chunks_org ON chunks(organization_id);
```

**Modelo de deployment:** cada cliente tiene su propio `organization_id`. Vos configurás todo, el cliente solo ve Notion.

---

### 3.4 SOPs y Weekly Rules por cliente `ALTO` `1d`

Cada cliente tiene su propio workspace de Notion. El orquestador lee del workspace correcto según `organization_id`.

**Configuración por cliente en `.env` o tabla `organizations`:**
```
ORG_NOVOLABS_NOTION_TOKEN=secret_...
ORG_NOVOLABS_NOTION_REELS_DB=uuid
ORG_CLIENTE2_NOTION_TOKEN=secret_...
ORG_CLIENTE2_NOTION_REELS_DB=uuid
```

---

### 3.5 Dashboard de ROI para el cliente `MEDIO` `2d`

Vista simple que muestra el valor del sistema al cliente.

**Métricas a mostrar:**
- Total de palabras generadas este mes
- Costo API real vs costo estimado copywriter humano (base: $0.15/palabra)
- Tasa de aprobación por formato (gráfico de barras)
- Top 5 entidades más usadas (salud del corpus)
- Evolución de ratings semana a semana

**Implementación:** nueva página en Streamlit o endpoint `/dashboard/{organization_id}`.

---

### 3.6 Limpieza de estructura de directorios `MEDIO` `1d`

El proyecto tiene estructura de POC mezclada con código de producción.

**Acciones:**
- [x] **Sub-agentes**: outputs en JSON estructurados listos para API.
- [x] **Endpoints (FastAPI)**: Base expuesta para `/health`, `/ingest`, `/generate/weekly`.
- [x] **Orchestrator Pattern**: Desacoplado con un job `WeeklyContentJob` funcional integrando Hybrid Search.
- [x] **Notion Async Client**: Lógica de storage configurada, rate limiting implementado localmente y schemas mapeados.

---

## Fase 4 — Packaging comercial
**Semanas 12–14 · Objetivo: cobrar como profesional**

> Implementar **solo cuando tengas al menos 3 clientes reales**. Antes de eso es especulativo.

### 4.1 Definición de tiers de servicio `MEDIO` `2d`

| Tier | Precio sugerido | Features |
|---|---|---|
| **Core** | $300-500/mes | Generación básica (texto), 50 piezas/semana, 1 formato |
| **Premium** | $700-1200/mes | Entidades + diversidad avanzada, 100 piezas/semana, todos los formatos, feedback loop |
| **Agency** | $1500-2500/mes | Multi-cliente, white label, acceso a dashboard, soporte prioritario |

**Nota:** El costo de API para 100 piezas/semana es ~$35-40/mes. El margen en tier Core es de ~$260-460/mes por cliente.

---

### 4.2 Gestión de API keys por cliente `MEDIO` `1d`

**Dos modelos:**

**Modelo A — Vos ponés la key (recomendado para empezar):**
- El cliente paga tarifa fija
- Vos manejás el costo de API
- Más simple de vender, más simple de operar
- Tu margen incluye el costo de API

**Modelo B — Cliente pone su key:**
- El cliente paga menos por el servicio
- Tiene control total de sus costos de LLM
- Requiere UI para que el cliente ingrese su key de forma segura
- Recomendado para tier Agency o clientes grandes

---

### 4.3 Documento de privacidad de datos `MEDIO` `1d`

**Con OpenAI API:**
> "Usamos la API de OpenAI para procesamiento de texto. Según los términos de OpenAI, los datos enviados via API no se usan para entrenar sus modelos. Tus transcripciones se procesan en memoria y se almacenan en nuestra base de datos encriptada."

**Con Ollama (opción "IA Privada"):**
> "El procesamiento de IA ocurre completamente en servidores dedicados. Tus datos nunca salen de tu entorno. Esta opción es ideal para empresas con requisitos de confidencialidad estrictos."

---

### 4.4 Budget Guard por cliente (extensión) `FÁCIL` `0.5d`

El Budget Guard ya existe. Solo hay que extenderlo con `organization_id`.

```python
def get_monthly_spent(organization_id: str = "default") -> float: ...
def record_cost(model: str, tokens_in: int, tokens_out: int,
                organization_id: str = "default") -> float: ...
```

---

### 4.5 Tests de integración del pipeline completo `MEDIO` `2d`

Sin tests, un bug puede quemar budget en silencio.

**Tests mínimos:**
```python
async def test_ingest_and_search():     # ingestar doc → buscar → encontrar
async def test_generate_and_publish():  # generar pieza → publicar en Notion mock
async def test_budget_guard():          # simular 90% de budget → verificar fallback
async def test_health_endpoint():       # GET /health con DB up y down
async def test_weekly_run_full():       # run completo con mocks de Notion y LLM
```

---

### 4.6 Circuit breaker para errores en cadena `MEDIO` `0.5d`

Más de 5 errores consecutivos → pausa el run → alerta Telegram → espera aprobación manual.

```python
class CircuitBreaker:
    max_consecutive_errors: int = 5
    
    async def execute(self, fn, *args):
        try:
            result = await fn(*args)
            self.reset()
            return result
        except Exception as e:
            self.record_error()
            if self.is_open():
                await telegram.notify_error("Circuit breaker abierto", str(e))
                raise CircuitBreakerOpenError()
            raise
```

---

## Decisiones de arquitectura clave

### Por qué modelo agencia, no SaaS

El producto actual está optimizado para un tipo específico de empresa (B2B, genera contenido de ventas y marketing, usa transcripciones de sesiones grupales). Venderlo como SaaS requeriría un nivel de configuración por cliente que hoy no existe. El modelo agencia te permite:
- Onboardear en 48 horas sin un panel de administración
- Aprender qué customiza cada cliente antes de construir esa customización
- Cobrar más (servicio gestionado > SaaS)
- Iterar rápido sin compatibilidad hacia atrás

Cuando tengas 10 clientes y patrones claros, tenés los insumos para construir el verdadero SaaS.

### Por qué Postgres y no Neo4j en Fase 1

El problema central es "dado un tópico, dame chunks relevantes". Eso es búsqueda vectorial con filtros, no traversal de grafos. Con metadata enriquecida (`topics`, `domain`, `emotion`, `entities`) y los índices GIN, Postgres resuelve ese problema completamente para el volumen actual. Neo4j agrega complejidad operacional y entity resolution como riesgo sin beneficio claro hasta tener decenas de miles de documentos.

### Por qué el feedback loop necesita datos primero

El prompt tuning automático (sin supervisión humana) puede degradar silenciosamente la calidad si el cliente califica de forma inconsistente. La versión correcta es: LLM analiza ratings bajos → propone ajuste → humano aprueba → se aplica al próximo run. Sin 3-4 semanas de ratings reales, no hay suficiente señal para que el análisis sea útil.

---

## Cronograma resumido

```
Semana 1-2   FastAPI + primeras pruebas de endpoints
Semana 2-3   Notion client + bases de datos configuradas
Semana 3-4   Orquestador + WeeklyContentJob
Semana 4-5   Refactorizar agentes + n8n + Telegram
             → MILESTONE: primer run real, 50 piezas en Notion
Semana 6     Plantilla Notion + script de validación
Semana 7     Flujo de aprobación en Notion + reporte semanal
Semana 8     Modo demo + guía de setup + PRIMER CLIENTE
             → MILESTONE: cliente real pagando
Semana 9-10  Feedback loop + sincronización de ratings
Semana 10-11 Multi-tenant + SOPs por cliente
Semana 11-12 Dashboard ROI + limpieza de estructura
             → MILESTONE: producto con retención demostrada
Semana 12-13 Tiers + documento de privacidad
Semana 13-14 Tests de integración + circuit breaker
             → MILESTONE: MVP vendible a escala
```

---

## Base técnica ya lista (no tocar)

- ✅ PostgreSQL + pgvector + schema v3.0 con metadata enriquecida
- ✅ Budget Guard con alertas 70%/90% y fallback automático
- ✅ Multi-provider LLM: OpenAI / Ollama / Gemini intercambiables via `.env`
- ✅ TaxonomyManager + extracción de entidades estilo LightRAG
- ✅ Hybrid search con diversity, entity scoring y RRF
- ✅ docker-compose con perfiles (local, graph, producción)
- ✅ Streamlit dashboard centralizado (Analíticas, Búsqueda, Ingesta, Configuración visual de `.env`)
- ✅ QA Gate programático (sin LLM por defecto) + retry automático
- ✅ `scripts/reset_db.sh` para cambio de proveedor
- ✅ Componentes Core Integrados (FastAPI `/health`, `/ingest`, API de config checks, Orquestador Base y Agentes JSON)

