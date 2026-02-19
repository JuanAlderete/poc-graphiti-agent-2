# POC: Validación Económica Graphiti Agent

Este proyecto implementa una Prueba de Concepto (POC) para validar la viabilidad económica de una arquitectura RAG Agéntica usando Graphiti, Neo4j, Postgres y LLMs (OpenAI/Gemini).

## Estructura del Proyecto

- `agent/`: Lógica base del agente (DB, Grafo, Tools).
- `ingestion/`: Pipeline de ingesta de documentos.
- `poc/`: Módulos específicos de la POC (Tracking de costos, queries de prueba, generación).
- `dashboard/`: Dashboard de Streamlit para visualizar resultados.
- `logs/`: Logs CSV generados por la ejecución.

## Configuración

1.  Crear entorno virtual e instalar dependencias:
    ```bash
    pip install -r requirements.txt
    ```

2.  Configurar variables de entorno en `.env`:
    ```env
    OPENAI_API_KEY=sk-...
    GEMINI_API_KEY=...
    NEO4J_URI=bolt://localhost:7687
    NEO4J_PASSWORD=password
    POSTGRES_PASSWORD=password
    # LLM_PROVIDER=openai  # o gemini
    ```

## Ejecución

### 1. Ejecutar POC Completa
Este comando ingesta documentos, corre búsquedas de prueba y genera contenido:

```bash
python -m poc.run_poc --all --ingest "path/to/docs"
```

Opciones:
- `--ingest <dir>`: Ingestar documentos desde un directorio.
- `--search`: Correr tests de búsqueda.
- `--generate`: Correr tests de generación.
- `--skip-checks`: Saltar chequeo de conexiones a DB.

### 2. Dashboard
Para visualizar los costos y métricas:

```bash
streamlit run dashboard/app.py
```

## Pruebas
Ejecutar tests unitarios:

```bash
pytest tests/poc/
```
