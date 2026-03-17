"""
api/routes/config_check.py
--------------------------
Endpoints para verificar credenciales desde el dashboard de configuración.
Solo se exponen internamente (no autenticados, asumir red privada).
"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/config", tags=["Configuración"])


class LLMCheckRequest(BaseModel):
    provider: str          # openai | ollama | gemini
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    gemini_api_key: Optional[str] = None


class NotionCheckRequest(BaseModel):
    token: str
    database_id: Optional[str] = None   # Para verificar acceso a una DB específica


class PostgresCheckRequest(BaseModel):
    host: str
    port: int = 5432
    database: str
    user: str
    password: str


class TelegramCheckRequest(BaseModel):
    bot_token: str
    chat_id: str


@router.post("/check/llm")
async def check_llm_credentials(req: LLMCheckRequest) -> dict:
    """Verifica que las credenciales del LLM son válidas."""
    try:
        if req.provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=req.api_key,
                base_url=req.base_url or None,
            )
            await client.models.list()
            return {"status": "ok", "message": "Conexión exitosa con OpenAI"}

        elif req.provider == "ollama":
            import httpx
            base = (req.base_url or "http://localhost:11434").rstrip("/v1").rstrip("/")
            async with httpx.AsyncClient(timeout=5.0) as c:
                resp = await c.get(f"{base}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                names = [m.get("name", "") for m in models]
                return {"status": "ok", "message": f"Ollama activo. Modelos: {', '.join(names[:5]) or 'ninguno descargado'}"}
            return {"status": "error", "message": f"Ollama respondió HTTP {resp.status_code}"}

        elif req.provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=req.gemini_api_key)
            models = list(genai.list_models())
            return {"status": "ok", "message": f"Gemini activo. {len(models)} modelos disponibles."}

        return {"status": "error", "message": f"Proveedor desconocido: {req.provider}"}

    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


@router.post("/check/notion")
async def check_notion_credentials(req: NotionCheckRequest) -> dict:
    """Verifica el token de Notion y opcionalmente el acceso a una DB."""
    try:
        from notion_client import AsyncClient
        client = AsyncClient(auth=req.token)
        # Verificar token básico: buscar usuario actual
        me = await client.users.me()
        name = me.get("name", "desconocido")

        if req.database_id:
            # Verificar acceso a la DB específica
            db = await client.databases.retrieve(database_id=req.database_id)
            db_title = db.get("title", [{}])
            title_text = db_title[0].get("plain_text", "sin nombre") if db_title else "sin nombre"
            return {"status": "ok", "message": f"Token válido (usuario: {name}). DB '{title_text}' accesible."}

        return {"status": "ok", "message": f"Token válido. Usuario: {name}"}

    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


@router.post("/check/postgres")
async def check_postgres_credentials(req: PostgresCheckRequest) -> dict:
    """Verifica la conexión a Postgres con las credenciales dadas."""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=req.host, port=req.port,
            database=req.database, user=req.user, password=req.password,
            timeout=5.0,
        )
        result = await conn.fetchval("SELECT version()")
        await conn.close()
        version = result.split(" ")[1] if result else "?"
        return {"status": "ok", "message": f"Postgres conectado (v{version})"}
    except Exception as e:
        msg = str(e)
        if "localhost" in req.host or "127.0.0.1" in req.host:
            msg += ". Nota: Si la API corre en Docker, 'localhost' es el contenedor. Usar 'postgres' o 'host.docker.internal'."
        return {"status": "error", "message": msg[:200]}


@router.post("/check/telegram")
async def check_telegram_credentials(req: TelegramCheckRequest) -> dict:
    """Verifica el bot token de Telegram enviando un mensaje de prueba."""
    try:
        import httpx
        # getMe para verificar el token
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(
                f"https://api.telegram.org/bot{req.bot_token}/getMe"
            )
        if resp.status_code != 200:
            return {"status": "error", "message": f"Token inválido (HTTP {resp.status_code})"}
        bot_info = resp.json().get("result", {})
        bot_name = bot_info.get("username", "?")

        # Enviar mensaje de prueba al chat_id
        async with httpx.AsyncClient(timeout=5.0) as c:
            send_resp = await c.post(
                f"https://api.telegram.org/bot{req.bot_token}/sendMessage",
                json={
                    "chat_id": req.chat_id,
                    "text": "✅ *Test de conexión exitoso* — MarketingMaker AI Engine",
                    "parse_mode": "Markdown",
                }
            )
        if send_resp.status_code == 200:
            return {"status": "ok", "message": f"Bot @{bot_name} activo. Mensaje de prueba enviado al chat."}
        else:
            err = send_resp.json().get("description", "error desconocido")
            return {"status": "error", "message": f"Bot válido pero no puede enviar al chat: {err}"}

    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}
