"""
config/notion_schema.py
-----------------------
Esquema central de nombres de propiedades para Notion.
Evita hardcodeos de nombres de propiedades en el cliente (storage/notion_client.py).
Permite ajustar fácilmente si la plantilla en Notion cambia.
"""

NOTION_SCHEMA = {
    # --------------------------------------------------------------------------
    # BASES DE CONFIGURACIÓN (Lectura)
    # --------------------------------------------------------------------------
    "weekly_rules": {
        "db_env_var": "NOTION_RULES_DB",
        "properties": {
            "formato": "Formato",    # type: select (reel_cta, historia, email, ads, reel_lead_magnet)
            "topico":  "Tópico",     # type: title/text
            "cantidad": "Cantidad",  # type: number
            "activo":  "Activo"      # type: checkbox
        }
    },
    
    # --------------------------------------------------------------------------
    # BASES DE PIEZAS GENERADAS (Escritura)
    # --------------------------------------------------------------------------
    "reel_cta": {
        "db_env_var": "NOTION_REELS_DB",
        "properties": {
            "title":                 "Hook",                    # type: title
            "hook":                  "Hook",                    # type: text
            "script":                "Script",                  # type: text
            "cta":                   "CTA",                     # type: text
            "sugerencias_grabacion": "Sugerencias de grabación",# type: text
            "copy":                  "Copy descripción",        # type: text
            "estado":                "Estado",                  # type: select (Propuesta, Aprobada, Rechazada, Regenerar)
            "rating":                "Rating",                  # type: select/number (1-5)
            "run_id":                "Run ID",                  # type: text
            "costo_usd":             "Costo USD",               # type: number
            "chunk_id":              "Chunk ID"                 # type: text
        }
    },
    
    "reel_lead_magnet": {
        "db_env_var": "NOTION_REELS_DB", 
        "properties": {
            "title":                 "Hook",                    # type: title
            "hook":                  "Hook",                    # type: text
            "problema":              "Problema",                # type: text
            "presentacion_lm":       "Presentación LM",         # type: text
            "cta":                   "CTA",                     # type: text
            "estado":                "Estado",
            "rating":                "Rating",
            "run_id":                "Run ID",
            "costo_usd":             "Costo USD",
            "chunk_id":              "Chunk ID"
        }
    },
    
    "historia": {
        "db_env_var": "NOTION_HISTORIA_DB",
        "properties": {
            "title":      "Tipo",       # type: title
            "tipo":       "Tipo",       # type: select
            "slides":     "Slides",     # type: text (combinado stringificado)
            "cta_final":  "CTA Final",  # type: text
            "estado":     "Estado",
            "rating":     "Rating",
            "run_id":     "Run ID",
            "costo_usd":  "Costo USD",
            "chunk_id":   "Chunk ID"
        }
    },
    
    "email": {
        "db_env_var": "NOTION_EMAIL_DB",
        "properties": {
            "title":     "Asunto",      # type: title
            "asunto":    "Asunto",      # type: text
            "preheader": "Preheader",   # type: text
            "cuerpo":    "Cuerpo",      # type: text
            "cta":       "CTA",         # type: text
            "ps":        "PS",          # type: text
            "estado":    "Estado",
            "rating":    "Rating",
            "run_id":    "Run ID",
            "costo_usd": "Costo USD",
            "chunk_id":  "Chunk ID"
        }
    },
    
    "ads": {
        "db_env_var": "NOTION_ADS_DB",
        "properties": {
            "title":         "Titulo Principal", # type: title
            "headlines":     "Headlines",        # type: text
            "descripciones": "Descripciones",    # type: text
            "copy":          "Copy",             # type: text
            "cta":           "CTA",              # type: text
            "visual":        "Visual",           # type: text
            "estado":        "Estado",
            "rating":        "Rating",
            "run_id":        "Run ID",
            "costo_usd":     "Costo USD",
            "chunk_id":      "Chunk ID"
        }
    },
    
    # --------------------------------------------------------------------------
    # REPORTES Y LOGS
    # --------------------------------------------------------------------------
    "weekly_runs": {
        "db_env_var": "NOTION_RUNS_DB",
        "properties": {
            "title":         "Run ID",       # type: title
            "fecha":         "Fecha",        # type: date
            "piezas":        "Piezas",       # type: number
            "aprobadas_qa":  "Aprobadas QA", # type: number
            "fallidas_qa":   "Fallidas QA",  # type: number
            "costo_usd":     "Costo Total",  # type: number
            "estado":        "Estado"        # type: select (Completado, Error)
        }
    }
}
