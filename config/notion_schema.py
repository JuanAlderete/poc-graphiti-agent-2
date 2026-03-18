"""
config/notion_schema.py
-----------------------
Esquema central de nombres de propiedades para Notion.
Evita hardcodeos de nombres de propiedades en el cliente (storage/notion_client.py).
Permite ajustar fácilmente si la plantilla en Notion cambia.

Tipos de propiedades en Notion (para referencia del builder):
  - title  → {"title": [...]}
  - select → {"select": {"name": "..."}}
  - text   → {"rich_text": [...]}
  - number → {"number": float}
  - date   → {"date": {"start": "YYYY-MM-DD"}}
"""

NOTION_SCHEMA = {
    # --------------------------------------------------------------------------
    # BASES DE CONFIGURACIÓN (Lectura)
    # --------------------------------------------------------------------------
    "weekly_rules": {
        "db_env_var": "NOTION_RULES_DB",
        "properties": {
            "formato": "Formato",    # type: select
            "topico":  "Tópico",     # type: title/text
            "cantidad": "Cantidad",  # type: number
            "activo":  "Activo"      # type: checkbox
        }
    },

    # --------------------------------------------------------------------------
    # BASES DE PIEZAS GENERADAS (Escritura)
    # Columnas verificadas con los CSV de muestra en /notion/*.csv
    # --------------------------------------------------------------------------

    # CSV header: Hook, Script, CTA, Sugerencias de grabacion, Copy descripcion,
    #             Estado, Rating, Run ID, Costo USD, Chunk ID, Formato, Topico, Fecha generacion
    "reel_cta": {
        "db_env_var": "NOTION_REELS_DB",
        "properties": {
            "title":                 "Hook",                     # type: title
            "script":                "Script",                   # type: text
            "cta":                   "CTA",                      # type: text
            "sugerencias_grabacion": "Sugerencias de grabacion", # type: text
            "copy":                  "Copy descripcion",         # type: text
            "estado":                "Estado",                   # type: select
            "rating":                "Rating",                   # type: number
            "run_id":                "Run ID",                   # type: select
            "costo_usd":             "Costo USD",                # type: number
            "chunk_id":              "Chunk ID",                 # type: text
            "formato":               "Formato",                  # type: select
            "topico":                "Topico",                   # type: text
            "fecha_generacion":      "Fecha generacion"          # type: date
        }
    },

    # reel_lead_magnet usa la misma DB que reel_cta (NOTION_REELS_DB).
    # Las columnas 'Problema' y 'Presentacion LM' no existen en esa tabla.
    # Se mapean los contenidos del formato a las columnas disponibles:
    # - problema    -> Script (texto de desarrollo)
    # - presentacion_lm -> Copy descripcion (el texto del lead magnet)
    "reel_lead_magnet": {
        "db_env_var": "NOTION_REELS_DB",
        "properties": {
            "title":             "Hook",                     # type: title
            "problema":          "Script",                   # reutiliza columna Script
            "presentacion_lm":   "Copy descripcion",         # reutiliza columna Copy
            "cta":               "CTA",                      # type: text
            "estado":            "Estado",                   # type: select
            "rating":            "Rating",                   # type: number
            "run_id":            "Run ID",                   # type: select
            "costo_usd":         "Costo USD",                # type: number
            "chunk_id":          "Chunk ID",                 # type: text
            "formato":           "Formato",                  # type: select
            "topico":            "Topico",                   # type: text
            "fecha_generacion":  "Fecha generacion"          # type: date
        }
    },

    # CSV header: Tipo, Slides, CTA Final, Estado, Rating, Run ID,
    #             Costo USD, Chunk ID, Tópico, Fecha generación
    # NOTA: la DB de historias NO tiene columna Formato.
    "historia": {
        "db_env_var": "NOTION_HISTORIA_DB",
        "properties": {
            "title":             "Tipo",              # type: title (= tipo de historia)
            "tipo":              "Tipo",              # type: select
            "slides":            "Slides",            # type: text
            "cta_final":         "CTA Final",         # type: text
            "estado":            "Estado",            # type: select
            "rating":            "Rating",            # type: number
            "run_id":            "Run ID",            # type: select
            "costo_usd":         "Costo USD",         # type: number
            "chunk_id":          "Chunk ID",          # type: text
            "topico":            "Tópico",            # type: text (acento en la DB)
            "fecha_generacion":  "Fecha generación"   # type: date (acento en la DB)
        }
    },

    # CSV header: Asunto, Preheader, Cuerpo, CTA, PS, Estado, Rating,
    #             Run ID, Costo USD, Chunk ID, Tópico, Fecha generación
    # NOTA: la DB de emails NO tiene columna Formato.
    "email": {
        "db_env_var": "NOTION_EMAIL_DB",
        "properties": {
            "title":             "Asunto",            # type: title
            "preheader":         "Preheader",         # type: text
            "cuerpo":            "Cuerpo",            # type: text
            "cta":               "CTA",               # type: text
            "ps":                "PS",                # type: text
            "estado":            "Estado",            # type: select
            "rating":            "Rating",            # type: number
            "run_id":            "Run ID",            # type: select
            "costo_usd":         "Costo USD",         # type: number
            "chunk_id":          "Chunk ID",          # type: text
            "topico":            "Tópico",            # type: text (acento en la DB)
            "fecha_generacion":  "Fecha generación"   # type: date (acento en la DB)
        }
    },

    # CSV header: Headlines, Descripciones, Copy, CTA, Visual, Estado, Rating,
    #             Run ID, Costo USD, Chunk ID, Tipo, Tópico, Fecha generación
    # NOTA: la DB de ads tiene columna "Tipo" (no "Formato").
    "ads": {
        "db_env_var": "NOTION_ADS_DB",
        "properties": {
            "title":             "Headlines",         # type: title (primer headline)
            "descripciones":     "Descripciones",     # type: text
            "copy":              "Copy",              # type: text
            "cta":               "CTA",               # type: text
            "visual":            "Visual",            # type: text
            "estado":            "Estado",            # type: rich_text (distinto al resto)
            "rating":            "Rating",            # type: number
            "run_id":            "Run ID",            # type: rich_text (distinto al resto)
            "costo_usd":         "Costo USD",         # type: number
            "chunk_id":          "Chunk ID",          # type: text
            "tipo":              "Tipo",              # type: select (awareness | etc.)
            "topico":            "Tópico",            # type: text (acento en la DB)
            "fecha_generacion":  "Fecha generación"   # type: date (acento en la DB)
        },
        # campos cuyo tipo difiere del comportamiento por defecto del builder
        "type_overrides": {
            "estado": "rich_text",
            "run_id": "rich_text",
        }
    },

    # --------------------------------------------------------------------------
    # REPORTES Y LOGS
    # --------------------------------------------------------------------------
    "weekly_runs": {
        "db_env_var": "NOTION_RUNS_DB",
        "properties": {
            "title":         "Run ID",              # type: title
            "fecha":         "Fecha",               # type: date
            "piezas":        "Total generadas",     # type: number
            "aprobadas_qa":  "Aprobadas QA",        # type: number
            "fallidas_qa":   "Fallidas",            # type: number
            "costo_usd":     "Costo USD",           # type: number
            "estado":        "Estado"               # type: select
        }
    }
}
