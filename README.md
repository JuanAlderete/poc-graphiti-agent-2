# POC: Graphiti Agent & Phased Rollout Strategy

Esta prueba de concepto (POC) implementa una arquitectura de **RAG Agéntico Híbrido** diseñada para ser económicamente viable y escalable. Combina la velocidad de **Postgres/pgvector** con la profundidad de razonamiento de **Graphiti/Neo4j**.

## 🚀 Estrategia de Despliegue (Phased Rollout)

El sistema está diseñado para evolucionar contigo, minimizando costos iniciales sin deuda técnica.

### 🔹 Fase 1: Lanzamiento Productivo (Vector-Only)
*Objetivo: Velocidad y Costo Mínimo.*
- **Motor**: Postgres (`pgvector`).
- **Modelo**: `text-embedding-3-small` (OpenAI) o `text-embedding-004` (Gemini).
- **Costo**: ~$0.02 USD / 1M tokens.
- **Uso**: Búsqueda semántica rápida y eficiente.
- **Comando**:
  ```bash
  python -m poc.run_poc --ingest "docs/" --skip-graphiti
  ```

### 🔹 Fase 1.5: Optimización de Metadatos
*Objetivo: Indexado Inteligente.*
- **Motor**: Python Script (sin costo LLM).
- **Acción**: Detecta automáticamente **YAML Frontmatter** en tus archivos Markdown y lo guarda estructuradamente.
- **Beneficio**: Prepara el terreno para un grafo más rico sin gastar ni un centavo extra hoy.
- **Ejemplo en Markdown**:
  ```yaml
  ---
  title: Guía de Ventas
  category: Playbook
  ---
  ```

### 🔹 Fase 2: Enriquecimiento con Grafo (Migración)
*Objetivo: Razonamiento Profundo.*
- **Motor**: Graphiti + Neo4j.
- **Modelo**: `gpt-5-mini` o `gpt-4o-mini`.
- **Acción**: Script de "hidratación" que lee de Postgres y construye el grafo.
- **Beneficio**: Conecta entidades y relaciones complejas para preguntas difíciles.
- **Comando**:
  ```bash
  python -m poc.hydrate_graph
  ```

---

## 🛠️ Instalación y Configuración

1.  **Requisitos**: Python 3.10+, Docker (para Neo4j/Postgres).
2.  **Instalar dependencias**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configurar entorno** (`.env`):
    ```env
    # Proveedor LLM (openai o gemini)
    LLM_PROVIDER=openai
    OPENAI_API_KEY=sk-...
    
    # Base de Datos
    POSTGRES_URI=postgresql://user:pass@localhost:5432/db
    NEO4J_URI=bolt://localhost:7687
    NEO4J_PASSWORD=password
    ```

## 📊 Dashboard y Métricas

El proyecto incluye un dashboard interactivo para visualizar costos, ejecutar pruebas y ver el rendimiento en tiempo real.

```bash
python -m streamlit run dashboard/app.py
```

### Funcionalidades del Dashboard:
- **Ingestion Tab**: Carga documentos con o sin grafo.
- **Search Tab**: Compara resultados Vectoriales vs. Grafo vs. Híbridos.
- **Analytics**: Visualiza el costo exacto por operación y modelo.

## 📂 Estructura del Proyecto

- `agent/`: Lógica central (Conexiones DB, Graphiti Wrapper, Herramientas de búsqueda).
- `ingestion/`: Pipeline de procesamiento (Chunking, Embeddings, Frontmatter parser).
- `poc/`: Scripts de validación económica, tracking de tokens y cálculo de costos.
- `dashboard/`: Interfaz de usuario Streamlit.
- `logs/`: Registros detallados de consumo y latencia (CSV).

## 💡 Notas de Arquitectura

- **Modelo de Precios**: Definido en `poc/config.py`. Incluye precios hipotéticos para modelos futuros (`gpt-5-mini`) y actuales.
- **Token Tracker**: Singleton thread-safe que cuenta tokens de entrada/salida para OpenAI y Gemini.
- **Metadata Injection**: El script de hidratación inyecta metadatos como contexto explícito al grafo para mejorar la desambiguación de entidades.
