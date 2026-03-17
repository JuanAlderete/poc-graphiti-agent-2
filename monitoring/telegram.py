"""
monitoring/telegram.py
----------------------
Cliente para envío de notificaciones por Telegram.

Usar:
    notifier = TelegramNotifier()
    await notifier.notify_ingestion("doc.md", 12, 0.003)
    await notifier.notify_weekly_results(run_id, 48, 45, 8.40)
    await notifier.notify_error("Error en generación", "stack trace...")
"""
import logging
from typing import Optional

import httpx

from poc.config import config

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Envía mensajes a un chat de Telegram via Bot API.

    Requiere:
        TELEGRAM_BOT_TOKEN = token del bot (obtener de @BotFather)
        TELEGRAM_CHAT_ID   = ID del chat/canal donde enviar
    """

    def __init__(self):
        self.token   = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.debug(
                "TelegramNotifier: deshabilitado "
                "(TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados)"
            )

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Envía un mensaje de texto. Retorna True si tuvo éxito."""
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id":    self.chat_id,
            "text":       text,
            "parse_mode": parse_mode,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code != 200:
                    logger.warning(
                        "Telegram respondió %d: %s",
                        response.status_code, response.text[:200]
                    )
                    return False
            return True
        except Exception as e:
            logger.warning("Error enviando mensaje a Telegram: %s", e)
            return False

    async def notify_ingestion(
        self,
        filename: str,
        chunks: int,
        cost_usd: float,
        entities: int = 0,
    ) -> None:
        """Notifica que se ingestionó un documento."""
        msg = (
            f"📥 *Documento ingestado*\n\n"
            f"📄 `{filename}`\n"
            f"🔢 {chunks} chunks creados\n"
        )
        if entities > 0:
            msg += f"🏷️ {entities} entidades extraídas\n"
        msg += f"💰 Costo: ${cost_usd:.4f}"
        await self.send_message(msg)

    async def notify_weekly_results(
        self,
        run_id: str,
        pieces_generated: int,
        pieces_qa_passed: int,
        cost_usd: float,
        notion_url: Optional[str] = None,
    ) -> None:
        """Notifica el resultado del run semanal."""
        from datetime import date

        approval_rate = (
            round(pieces_qa_passed / pieces_generated * 100, 1)
            if pieces_generated > 0 else 0
        )
        status_emoji = "✅" if pieces_qa_passed >= pieces_generated * 0.8 else "⚠️"

        msg = (
            f"📊 *Run semanal completado — {date.today().strftime('%d %b %Y')}*\n\n"
            f"{status_emoji} {pieces_generated} piezas generadas\n"
            f"👍 {pieces_qa_passed} aprobadas por QA ({approval_rate}%)\n\n"
            f"💰 Costo total: ${cost_usd:.2f}\n"
            f"🔤 ~{pieces_qa_passed * 500:,} palabras generadas\n\n"
            f"⏳ *{pieces_qa_passed} piezas esperando tu revisión en Notion*"
        )
        if notion_url:
            msg += f"\n\n🔗 [Ver en Notion]({notion_url})"

        await self.send_message(msg)

    async def notify_error(self, context: str, error: str) -> None:
        """Notifica un error crítico."""
        msg = (
            f"🚨 *Error en MarketingMaker AI Engine*\n\n"
            f"📍 Contexto: {context}\n"
            f"❌ Error: `{error[:300]}`"
        )
        await self.send_message(msg)

    async def notify_budget_alert(
        self,
        pct: float,
        spent_usd: float,
        budget_usd: float,
        active_model: str,
    ) -> None:
        """Notifica alerta de presupuesto."""
        if pct >= 90:
            emoji = "🔴"
            action = f"Modelo fallback activado: `{active_model}`"
        else:
            emoji = "🟡"
            action = "Considera revisar el uso de API"

        msg = (
            f"{emoji} *Alerta de presupuesto*\n\n"
            f"💸 Gastado: ${spent_usd:.2f} de ${budget_usd:.2f} ({pct:.1f}%)\n"
            f"⚡ {action}"
        )
        await self.send_message(msg)