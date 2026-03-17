# Workflows de n8n — Novolabs AI Engine

Los workflows de n8n se configuran manualmente en la interfaz web
y se exportan como JSON. No se generan automáticamente.

## Workflows a configurar

### 1. novolabs_ingesta_drive
- Trigger: Google Drive → carpeta específica, archivo nuevo
- Nodo 1: HTTP Request GET http://localhost:8000/health (verificar sistema)
- Nodo 2: Leer contenido del archivo de Drive
- Nodo 3: HTTP Request POST http://localhost:8000/ingest con {filename, content}
- Nodo 4: Telegram (notificar éxito o error)

### 2. novolabs_generacion_semanal  
- Trigger: Cron — domingo 23:00
- Nodo 1: HTTP Request GET http://localhost:8000/health
- Nodo 2 (condicional): Si health.status != "ok", notificar error y detener
- Nodo 3: HTTP Request POST http://localhost:8000/generate/weekly con {"dry_run": false}
- Nodo 4: Telegram (reporte del resultado)

## Variables de entorno en n8n
- NOVOLABS_API_URL = http://tu-servidor:8000
- TELEGRAM_CHAT_ID (para notificaciones de error desde n8n)
