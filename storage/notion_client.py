"""
storage/notion_client.py
------------------------
Cliente Async de Notion con rate-limiting centralizado.
Integra `config/notion_schema.py` para mapear dinámicamente propiedades.
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List

from notion_client import AsyncClient
from notion_client.errors import APIResponseError

from poc.config import config
from config.notion_schema import NOTION_SCHEMA

logger = logging.getLogger(__name__)


class NotionClient:
    """
    Cliente envuelto de Notion.
    Maneja el Rate Limiting global (máximo 3 peticiones por segundo).
    Soporta modelo Multi-tenant usando get_notion_token de config.
    """
    def __init__(self, organization_id: str = "default"):
        # En una arquitectura fully multi-tenant, config debería resolver esto por org_id.
        # Por ahora para MVP mapeamos sobre la instancia única o extendible:
        token = getattr(config, f"ORG_{organization_id.upper()}_NOTION_TOKEN", config.NOTION_TOKEN)
        
        if not token:
            logger.warning(f"NotionClient: No se encontró token para organization_id='{organization_id}'")
            
        self.client = AsyncClient(auth=token) if token else None
        
        # RATE LIMITING: Minimo 0.34s (3 requests per sec appx)
        self._last_request_time = 0.0
        self._min_interval = 0.34  

    async def _request(self, method_coro, *args, **kwargs) -> Any:
        """
        Wrapper que asegura el rate-limit antes de cada llamada a Notion.
        method_coro debe ser el callable asíncrono del cliente Notion real.
        """
        if not self.client:
            logger.error("NotionClient no está inicializado (Token faltante).")
            return None

        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
            
        self._last_request_time = time.time()
        
        try:
            return await method_coro(*args, **kwargs)
        except APIResponseError as e:
            logger.error(f"Error de API Notion: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error inesperado llamando a Notion: {e}")
            raise e

    # -------------------------------------------------------------------------
    # WEEKLY RULES & SOPs
    # -------------------------------------------------------------------------
    async def get_weekly_rules(self) -> List[Dict[str, Any]]:
        """
        Lee la base de datos de Weekly Rules configurada por el cliente.
        Si la base de datos está vacía o hubo error o no está configurada, retorna vacío,
        deleando la resolución de `DEFAULT_WEEKLY_RULES` en el orquestador.
        """
        schema_entry = NOTION_SCHEMA["weekly_rules"]
        db_env_var = schema_entry["db_env_var"]
        db_id = getattr(config, db_env_var, None)
        if not db_id:
            logger.warning(f"No hay {db_env_var} configurado.")
            return []
            
        schema = NOTION_SCHEMA["weekly_rules"]["properties"]

        try:
            response = await self._request(
                self.client.databases.query,
                database_id=db_id,
                filter={
                    "property": schema["activo"],
                    "checkbox": {"equals": True}
                }
            )
            
            rules = []
            if response and "results" in response:
                for page in response["results"]:
                    props = page["properties"]
                    
                    # Extrayendo valores basando el parseo en los tipos Notion.
                    rule_format = _extract_property_value(props.get(schema["formato"]), "select")
                    rule_topic = _extract_property_value(props.get(schema["topico"]), "title")
                    rule_qty = _extract_property_value(props.get(schema["cantidad"]), "number")
                    
                    if rule_format and rule_topic and rule_qty is not None:
                        rules.append({
                            "formato": rule_format,
                            "topico": rule_topic,
                            "cantidad": int(rule_qty)
                        })
            return rules
        except Exception as e:
            logger.error(f"Error obteniendo Weekly Rules: {e}")
            return []

    async def get_sop(self, format_name: str) -> Optional[str]:
        """
        (Opcional) Leer el SOP para el subagente desde Notion.
        Si en MVP no se usa SOP desde Notion para este formato, retorna None.
        """
        logger.info("NotionClient.get_sop - No implementado en M1, fallback a string defaults en agentes.")
        return None

    # -------------------------------------------------------------------------
    # PUBLICACIÓN
    # -------------------------------------------------------------------------
    async def publish_piece(self, content_type: str, piece_data: Dict[str, Any]) -> Optional[str]:
        """
        Publica una pieza en Notion, basándose en el mapeo de `NOTION_SCHEMA`.
        Retorna el `page_id` insertado o None si falló.
        No interrumpe el run si falla.
        """
        schema_entry = NOTION_SCHEMA.get(content_type)
        if not schema_entry:
            logger.error(f"publish_piece: formato '{content_type}' no tiene schema definido")
            return None
            
        db_env_var = schema_entry["db_env_var"]
        db_id = getattr(config, db_env_var, None)
        
        if not db_id:
            logger.error(f"publish_piece: variable {db_env_var} no configurada")
            return None

        props_map = schema_entry["properties"]
        notion_properties = {}

        # Mapeamos lo que llega de piece_data a las propiedades de notion
        # Asume que un piece_data puede contener: title, hook, script, cta, estado, rating, chunk_id, etc.
        for internal_key, value in piece_data.items():
            if internal_key in props_map and value is not None:
                notion_prop_name = props_map[internal_key]
                # Determinamos el type dependiendo de internal_key por convención o esquema
                notion_properties[notion_prop_name] = _build_notion_property(internal_key, value)

        try:
            resp = await self._request(
                self.client.pages.create,
                parent={"database_id": db_id},
                properties=notion_properties
            )
            return resp.get("id") if resp else None
        except Exception as e:
            logger.error(f"Error publicando pieza de formato {content_type}: {e}")
            # Retornar None habilita falla elástica, no revienta el Run entero.
            return None

    async def create_weekly_run(self, run_id: str, results_summary: Dict[str, Any]) -> None:
        """
        Loguea el Weekly Run final hacia Notion (opcional).
        """
        schema_entry = NOTION_SCHEMA.get("weekly_runs")
        if not schema_entry:
            return
            
        db_env_var = schema_entry["db_env_var"]
        db_id = getattr(config, db_env_var, None)
        
        if not db_id:
            return
            
        schema = schema_entry["properties"]
        
        notion_properties = {
            schema["title"]: _build_notion_property("title", run_id),
            schema["piezas"]: _build_notion_property("number", results_summary.get("total", 0)),
            schema["aprobadas_qa"]: _build_notion_property("number", results_summary.get("passed", 0)),
            schema["fallidas_qa"]: _build_notion_property("number", results_summary.get("failed", 0)),
            schema["costo_usd"]: _build_notion_property("number", results_summary.get("cost_usd", 0.0)),
        }

        try:
            await self._request(
                self.client.pages.create,
                parent={"database_id": db_id},
                properties=notion_properties
            )
        except Exception as e:
            logger.error(f"Error publicando reporte Weekly Run {run_id}: {e}")

    async def update_piece_status(self, page_id: str, new_status: str) -> bool:
        """
        Actualiza propiedad 'Estado'. (Generalmente para Flujo de aprobación Notion)
        """
        try:
            # En todos los esquemas, la propiedad de estado suele llamarse "Estado"
            await self._request(
                self.client.pages.update,
                page_id=page_id,
                properties={
                    "Estado": {"select": {"name": new_status}}
                }
            )
            return True
        except Exception as e:
            logger.error(f"Error actualizando Estado para page {page_id}: {e}")
            return False


# =============================================================================
# HELPER PARSERS
# =============================================================================

def _extract_property_value(prop_data: Optional[Dict], prop_type: str) -> Any:
    """Extrae valor limpio de un nodo de prop de Notion Query"""
    if not prop_data:
        return None
    try:
        if prop_type == "select" and "select" in prop_data and prop_data["select"]:
            return prop_data["select"].get("name")
        elif prop_type == "title" and "title" in prop_data and len(prop_data["title"]) > 0:
            return prop_data["title"][0]["plain_text"]
        elif prop_type == "text" and "rich_text" in prop_data and len(prop_data["rich_text"]) > 0:
            return "".join([t["plain_text"] for t in prop_data["rich_text"]])
        elif prop_type == "number" and "number" in prop_data:
            return prop_data["number"]
        elif prop_type == "checkbox" and "checkbox" in prop_data:
            return prop_data["checkbox"]
    except Exception as e:
        pass
    return None

def _build_notion_property(internal_key: str, value: Any) -> Dict[str, Any]:
    """
    Construye la estructura de objeto Notion para Types.
    Mapeo heurístico sencillo.
    """
    if internal_key == "title":
        return {"title": [{"text": {"content": str(value)[:2000]}}]}
    
    elif internal_key in ["estado", "formato", "tipo"]:
        return {"select": {"name": str(value)}}
        
    elif internal_key in ["cantidad", "rating", "costo_usd", "number"]:
        return {"number": float(value)}
        
    elif internal_key in ["activo"]:
        return {"checkbox": bool(value)}
        
    else:
        # Fallback a text / rich_text (capping en 2000 char per limite notion por blq)
        v = str(value)[:2000]
        return {"rich_text": [{"text": {"content": v}}]}
