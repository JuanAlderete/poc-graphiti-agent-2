# Plan de Implementación: POC de Validación Económica Novolabs

## Objetivo

Validar si la arquitectura **Graphiti + PostgreSQL/pgvector** es económicamente viable, midiendo costos de ingesta, búsqueda y generación de contenido.

---

## Decisiones de Diseño

| Aspecto | Decisión |
|---------|----------|
| Base de datos | PostgreSQL + pgvector (mantener actual) |
| Modelo LLM | gpt-5-mini |
| Documentos de prueba | 10 de `big_tech_docs/` |
| Generación | Implementar módulo básico |
| Entregables | CSVs + Dashboard Streamlit |

---

## Estructura de Archivos a Crear

```
poc-graphiti-agent/
├── poc/                              # NUEVO - Módulo principal
│   ├── __init__.py
│   ├── config.py                     # Precios de modelos
│   ├── token_tracker.py              # Tracking central de tokens
│   ├── cost_calculator.py            # Calculadora de costos USD
│   ├── logging_utils.py              # Utilidades para logs CSV
│   ├── content_generator.py          # Generador de contenido
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── reel_cta.py
│   │   ├── reel_lead_magnet.py
│   │   ├── historia.py
│   │   └── email.py
│   ├── run_poc.py                    # Script principal
│   └── queries.py                    # 20 queries de prueba
├── dashboard/                        # NUEVO - Dashboard Streamlit
│   ├── __init__.py
│   ├── app.py                        # App principal
│   └── utils.py
├── logs/                             # NUEVO - Logs CSV
│   ├── ingesta_log.csv
│   ├── busqueda_log.csv
│   └── generacion_log.csv
└── tests/poc/                        # NUEVO - Tests
    ├── test_token_tracker.py
    └── test_cost_calculator.py
```

---

## Archivos Existentes a Modificar

### 1. `ingestion/ingest.py`
**Líneas 161-269** - Agregar tracking en `_ingest_single_document()`:
- Capturar tokens de preproceso, graphiti y embeddings
- Calcular costo USD por documento
- Registrar en `ingesta_log.csv`

### 2. `agent/tools.py`
**Líneas 104-213** - Instrumentar búsquedas:
- `vector_search_tool()` - tracking de tokens/latencia
- `graph_search_tool()` - tracking de tokens/latencia
- `hybrid_search_tool()` - tracking de tokens/latencia
- Registrar en `busqueda_log.csv`

### 3. `ingestion/embedder.py`
**Líneas 74-172** - Capturar tokens:
- Modificar `generate_embedding()` para retornar tokens usados
- Modificar `generate_embeddings_batch()` para tracking

### 4. `agent/graph_utils.py`
- Instrumentar `GraphitiClient.add_episode()` para capturar tokens LLM

---

## Esquema de Logs CSV

### `ingesta_log.csv`
```
episodio_id, timestamp, source_type, nombre_archivo, longitud_palabras,
orden_ingesta, contexto_grafo, preproceso_tokens_in, preproceso_tokens_out,
graphiti_tokens_in, graphiti_tokens_out, embeddings_tokens,
entidades_extraidas, relaciones_creadas, chunks_creados, tiempo_seg,
costo_preproceso_usd, costo_graphiti_usd, costo_embeddings_usd, costo_total_usd
```

### `busqueda_log.csv`
```
query_id, timestamp, query_texto, longitud_query, contexto_grafo,
tipo_busqueda, tokens_embedding, tokens_llm_in, tokens_llm_out,
costo_embedding_usd, costo_llm_usd, costo_total_usd,
resultados_retornados, latencia_ms
```

### `generacion_log.csv`
```
pieza_id, timestamp, formato, tema_base, tokens_contexto_in,
tokens_prompt_in, tokens_out, modelo, costo_usd, tiempo_seg,
longitud_output_chars
```

---

## Fases de Implementación

### Fase 1: Infraestructura Base
1. Crear estructura `poc/` y `dashboard/`
2. Implementar `poc/config.py` con precios de modelos
3. Implementar `poc/token_tracker.py`
4. Implementar `poc/cost_calculator.py`
5. Implementar `poc/logging_utils.py`
6. Crear directorio `logs/`

### Fase 2: Instrumentación de Ingesta
1. Modificar `ingestion/embedder.py` para retornar tokens
2. Modificar `ingestion/ingest.py` para tracking completo
3. Crear wrapper de tracking para Graphiti
4. Probar ingesta de 1 documento con logs

### Fase 3: Instrumentación de Búsqueda
1. Modificar `agent/tools.py` para tracking de búsquedas
2. Implementar `poc/queries.py` con 20 queries de prueba
3. Probar búsquedas con logs

### Fase 4: Módulo de Generación
1. Implementar `poc/content_generator.py`
2. Crear prompts para cada formato (reel_cta, reel_lead_magnet, historia, email)
3. Probar generación de 1 pieza de cada tipo

### Fase 5: Script de Ejecución
1. Implementar `poc/run_poc.py`
2. Ejecutar POC completa:
   - 10 documentos de `big_tech_docs/`
   - 20 búsquedas variadas (vector, graph, hybrid)
   - 5 piezas de contenido
3. Verificar logs CSV

### Fase 6: Dashboard Streamlit
1. Implementar `dashboard/app.py` con 5 tabs:
   - Ingesta: métricas y distribución de costos
   - Búsquedas: costos por tipo, latencias
   - Generación: costos por formato
   - Proyecciones: mensual/anual con parámetros ajustables
   - Optimizaciones: matriz de oportunidades

### Fase 7: Tests y Documentación
1. Crear tests para `token_tracker` y `cost_calculator`
2. Actualizar README con instrucciones de POC

---

## Componentes Clave

### TokenTracker (poc/token_tracker.py)
```python
class TokenTracker:
    def start_operation(operation_type, metadata) -> operation_id
    def record_tokens(tokens_in, tokens_out, model, sub_operation)
    def end_operation() -> OperationMetrics
```

### CostCalculator (poc/cost_calculator.py)
```python
MODEL_PRICING = {
    "gpt-5-mini": ModelPricing(0.20, 0.80),  # USD por 1M tokens
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "text-embedding-3-small": ModelPricing(0.02, 0.0),
}

def calculate_cost(tokens_in, tokens_out, model) -> float
```

### ContentGenerator (poc/content_generator.py)
```python
class ContentGenerator:
    async def generate(formato, tema, contexto_adicional) -> GeneratedContent

# Formatos soportados: reel_cta, reel_lead_magnet, historia, email
```

### Dashboard (dashboard/app.py)
- Tab Ingesta: pie chart de costos, tabla detallada
- Tab Búsquedas: histograma de latencias, costos por tipo
- Tab Generación: barras de costo por formato
- Tab Proyecciones: inputs para docs/mes, queries/mes, piezas/mes → proyección anual
- Tab Optimizaciones: matriz con ahorro estimado, impacto y prioridad

---

## 20 Queries de Prueba

| # | Query | Tipo |
|---|-------|------|
| 1-5 | Búsquedas semánticas sobre valuación, estrategias, roles | vector |
| 6-10 | Relaciones entre entidades (OpenAI-Microsoft, inversores) | graph |
| 11-15 | Comparativas y análisis comprehensivos | hybrid |
| 16-20 | Edge cases y queries específicas | mixto |

---

## Verificación

### Checklist
- [ ] `logs/ingesta_log.csv` tiene 10 registros con todos los campos
- [ ] `logs/busqueda_log.csv` tiene 20 registros
- [ ] `logs/generacion_log.csv` tiene 5 registros
- [ ] Dashboard muestra datos correctamente
- [ ] Proyecciones calculan sin errores

### Comandos de Ejecución
```bash
# Activar entorno virtual
source venv_linux/bin/activate

# Ejecutar POC completa
python3 -m poc.run_poc

# Iniciar Dashboard
streamlit run dashboard/app.py
```

---

## Dependencias Adicionales

```
streamlit>=1.30.0
plotly>=5.18.0
```

---

## Criterios de Éxito (de la especificación)

| Decisión | Costo/Episodio | Costo Mensual | Costo Anual |
|----------|----------------|---------------|-------------|
| **GO** | < $0.40 | < $100 | < $1,500 |
| **OPTIMIZE** | $0.40-0.70 | $100-200 | $1,500-3,000 |
| **STOP** | > $0.70 | > $200 | > $3,000 |

---

## Archivos Críticos a Modificar

1. `ingestion/ingest.py:161-269` - Pipeline de ingesta
2. `agent/tools.py:104-213` - Herramientas de búsqueda
3. `ingestion/embedder.py:74-172` - Generador de embeddings
4. `agent/models.py:103-232` - Modelos Pydantic
5. `agent/providers.py:16-128` - Configuración de proveedores
