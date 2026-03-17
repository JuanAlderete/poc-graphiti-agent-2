"""
orchestrator/main.py
--------------------
Orquestador Principal, sirve como punto de acceso único desde clientes web, APIs o CRONs.
"""
import logging
from typing import List, Dict, Any

from orchestrator.weekly_job import WeeklyContentJob
from storage.notion_client import NotionClient

logger = logging.getLogger(__name__)

class MainOrchestrator:
    """
    MainOrchestrator coordina las ejecuciones maestras. 
    En esta fase, la operación principal es la de Content Generation Semanal (Job).
    """
    def __init__(self, run_id: str, org_id: str = "default", dry_run: bool = False):
        self.run_id = run_id
        self.org_id = org_id
        self.dry_run = dry_run
        
    async def run(self, formats_override: list = None) -> Dict[str, Any]:
        """
        Ejecuta el WeeklyContentJob principal para generar contenido.
        
        Args:
            formats_override: Si se pasa, actúa como un mock temporal o sobreescritura 
                              bypassando NotionDB para dictar qué formatos generar.
        """
        logger.info(f"MainOrchestrator Iniciando RUN [{self.run_id}] para org: {self.org_id}")
        
        # 1. Instanciar Job Específico
        job = WeeklyContentJob(org_id=self.org_id, dry_run=self.dry_run)
        
        # 2. Requerimientos
        if formats_override:
             rules = formats_override
             logger.info(f"Usando formats_override del request: {rules}")
        else:
             rules = await job.get_requirements()
             
        if not rules:
             # Fallback final a código si Notion está vacío y no hay overrides.
             logger.warning("MainOrchestrator: No hay reglas en Notion. Fallback hardcodeado usado.")
             rules = [
                 {"formato": "reel_cta", "cantidad": 2, "topico": "PMF"},
                 {"formato": "email", "cantidad": 1, "topico": "Ventas"}
             ]
             
        # 3. Procesar Cadenas
        all_pieces = []
        total_passed = 0
        total_failed = 0
        total_cost = 0.0

        for rule in rules:
             logger.info(f"MainOrchestrator ejecutando Regla: {rule}")
             rule_result = await job.run_rule(rule, run_id=self.run_id)
             all_pieces.extend(rule_result["pieces"])
             total_passed += len(rule_result["pieces"])
             total_failed += rule_result["failed_count"]
             total_cost += rule_result["total_cost"]
             
        # 4. Reporte Final y Storage Summary
        summary = {
             "total":    total_passed + total_failed,
             "passed":   total_passed,
             "failed":   total_failed,
             "cost_usd": round(total_cost, 6),
        }
        
        if not self.dry_run:
            notion = NotionClient(organization_id=self.org_id)
            await notion.create_weekly_run(self.run_id, summary)

        logger.info(f"MainOrchestrator Run [{self.run_id}] Finalizado. Piezas generadas/aprobadas: {total_passed}")
        
        try:
            from monitoring.telegram import TelegramNotifier
            telegram = TelegramNotifier()
            await telegram.notify_weekly_results(
                run_id=self.run_id,
                pieces_generated=summary["total"],
                pieces_qa_passed=summary["passed"],
                cost_usd=summary["cost_usd"],
            )
        except Exception as e:
            logger.warning("Telegram notify falló (no crítico): %s", e)
        
        return {
             "status": "success",
             "run_id": self.run_id,
             "pieces_generated": len(all_pieces),
             "summary": summary,
             "details": all_pieces
        }
