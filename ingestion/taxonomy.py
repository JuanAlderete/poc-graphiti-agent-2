import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC SCHEMAS PARA EXTRACCIÓN ESTRUCTURADA
# =============================================================================

class Entity(BaseModel):
    """Una entidad extraída de un chunk de texto."""
    name: str
    type: str
    # Tipos esperados: Concepto, Persona, Organización, Herramienta,
    #                  Etapa de Proceso, Emoción, Métrica, Estrategia


class Relationship(BaseModel):
    """Relación entre dos entidades en formato Sujeto-Verbo-Objeto."""
    subject: str
    relation: str
    object: str


class EntityExtractionResult(BaseModel):
    """Resultado completo de la extracción de entidades de un chunk."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []


# =============================================================================
# CONSTANTES DE CLASIFICACIÓN POR KEYWORDS (sin LLM — siempre disponible)
# =============================================================================

SOURCE_TYPE_PATTERNS: dict[str, list[str]] = {
    "llamada_venta":  ["llamada", "venta", "closer", "cierre", "prospecto", "sales_call"],
    "sesion_grupal":  ["sesion", "sesión", "grupal", "grupo", "cohorte", "masterclass", "clase"],
    "podcast":        ["podcast", "episodio", "episode", "ep_", "ep-"],
    "masterclass":    ["masterclass", "master_class", "taller", "workshop"],
    "email":          ["email", "newsletter", "correo"],
    "entrevista":     ["entrevista", "interview"],
}

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "ventas": [
        "venta", "ventas", "cliente", "objecion", "objeción", "cierre", "propuesta",
        "pricing", "precio", "negociacion", "negociación", "prospecto", "lead",
        "funnel", "conversion", "conversión", "closer", "discovery", "llamada",
    ],
    "marketing": [
        "reel", "contenido", "instagram", "linkedin", "copy", "copywriting", "hook",
        "audiencia", "engagement", "marca", "branding", "storytelling", "cta",
        "anuncio", "ads", "campaña", "post", "historia", "story", "tráfico",
    ],
    "producto": [
        "producto", "feature", "funcionalidad", "desarrollo", "mvp", "roadmap",
        "usuario", "ux", "feedback", "iteración", "prototipo", "release",
    ],
    "metodologia": [
        "metodología", "metodologia", "proceso", "framework", "sistema", "estructura",
        "modelo", "estrategia", "planificación", "planning", "sprint", "agile",
        "validación", "validacion", "hipótesis", "hipotesis", "experimentar",
    ],
}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "validacion":         ["validar", "validación", "hipótesis", "mvp", "idea", "mercado"],
    "objeciones":         ["objeción", "objeciones", "pero", "no puedo", "muy caro", "no tengo"],
    "pricing":            ["precio", "pricing", "caro", "barato", "inversión", "costo", "cobrar"],
    "miedos":             ["miedo", "miedos", "inseguridad", "dudas", "incertidumbre", "riesgo"],
    "liderazgo":          ["liderazgo", "equipo", "contratar", "delegar", "cultura", "gestión"],
    "emprendimiento":     ["emprender", "emprendimiento", "startup", "negocio", "empresa"],
    "ventas_b2b":         ["b2b", "empresa", "corporativo", "cuenta", "deal", "contrato"],
    "mindset":            ["mentalidad", "mindset", "actitud", "creencias", "cambio", "fracaso"],
    "productividad":      ["productividad", "tiempo", "prioridades", "foco", "hábitos", "rutina"],
    "marketing_digital":  ["instagram", "linkedin", "redes sociales", "contenido", "algoritmo"],
    "storytelling":       ["historia", "storytelling", "narrativa", "cuento", "anécdota", "ejemplo"],
    "finanzas":           ["finanzas", "flujo de caja", "inversión", "facturación", "mrr", "arr"],
}

EMOTION_KEYWORDS: dict[str, list[str]] = {
    "miedo":       ["miedo", "asustado", "nervioso", "pánico", "terror", "temor", "preocupado"],
    "frustracion": ["frustrado", "frustración", "harto", "cansado", "no funciona", "imposible", "rendirse"],
    "win":         ["éxito", "logré", "funcionó", "increíble", "resultado", "cerré", "gané", "conseguí"],
    "motivacion":  ["motivado", "energía", "ganas", "entusiasmo", "pasión", "inspirado", "creer"],
    "neutral":     [],
}

SPEAKER_ROLE_PATTERNS: dict[str, list[str]] = {
    "fundador":  ["fundador", "founder", "ceo", "co-founder", "cofundador"],
    "alumno":    ["alumno", "estudiante", "participante", "cohorte"],
    "mentor":    ["mentor", "coach", "consultor", "advisor"],
    "closer":    ["closer", "vendedor", "sales", "comercial"],
}

ADVANCED_VOCABULARY = [
    "propuesta de valor", "customer success", "churn", "ltv", "cac",
    "unit economics", "burn rate", "runway", "term sheet", "due diligence",
    "go to market", "product market fit", "pmf", "arpu", "mrr", "arr",
    "north star metric", "okr", "cohort", "retention", "nps",
]

BASIC_VOCABULARY = [
    "qué es", "cómo funciona", "para empezar", "primer paso",
    "básico", "introductorio", "principiante", "aprender",
]

# Prompt estilo LightRAG para extracción de entidades
_ENTITY_EXTRACTION_PROMPT = """Analiza el siguiente texto y extrae las entidades y relaciones más relevantes para la creación de contenido de marketing y ventas.

TEXTO:
{text}

INSTRUCCIONES:
- Extrae entre 3 y 7 entidades clave (conceptos, personas, herramientas, etapas de proceso, emociones, métricas, estrategias)
- Para cada entidad, identifica su tipo
- Si hay relaciones lógicas claras entre entidades, extráelas en formato Sujeto-Relación-Objeto
- Máximo 4 relaciones
- Solo incluye lo que es realmente relevante para crear contenido educativo o de ventas
- Los nombres de entidades deben estar en español

Responde ÚNICAMENTE con JSON válido sin texto adicional:
{{
  "entities": [
    {{"name": "nombre de la entidad", "type": "tipo"}}
  ],
  "relationships": [
    {{"subject": "entidad A", "relation": "verbo que describe la relación", "object": "entidad B"}}
  ]
}}"""


# =============================================================================
# DATA CLASS DE METADATA
# =============================================================================

@dataclass
class ChunkMetadata:
    """
    Metadata enriquecida de un chunk, lista para insertar en Postgres.
    Ahora incluye entities y relationships extraídas por LLM.
    """
    source_type:    str = "otro"
    speaker_role:   str = "desconocido"
    topics:         list[str] = field(default_factory=list)
    content_level:  int = 1
    emotion:        str = "neutral"
    domain:         str = "metodologia"
    edition:        Optional[int] = None
    alumno_id:      Optional[str] = None
    fecha:          Optional[str] = None
    used_count:     int = 0
    last_used_at:   None = None
    is_deleted:     bool = False

    # NUEVO: entidades y relaciones extraídas por LLM (estilo LightRAG)
    entities:       list[dict] = field(default_factory=list)
    # Formato: [{"name": "Cierre de ventas", "type": "Etapa de Proceso"}, ...]

    relationships:  list[dict] = field(default_factory=list)
    # Formato: [{"subject": "X", "relation": "dificulta", "object": "Y"}, ...]

    def to_dict(self) -> dict:
        return {
            "source_type":    self.source_type,
            "speaker_role":   self.speaker_role,
            "topics":         self.topics,
            "content_level":  self.content_level,
            "emotion":        self.emotion,
            "domain":         self.domain,
            "edition":        self.edition,
            "alumno_id":      self.alumno_id,
            "fecha":          self.fecha or date.today().isoformat(),
            "used_count":     self.used_count,
            "last_used_at":   self.last_used_at,
            "is_deleted":     self.is_deleted,
            "entities":       self.entities,
            "relationships":  self.relationships,
        }


# =============================================================================
# TAXONOMY MANAGER
# =============================================================================

class TaxonomyManager:
    """
    Clasifica y enriquece chunks en el momento de la ingesta.

    Tiene dos modos:
    1. KEYWORDS (siempre disponible, gratis): clasifica source_type, domain,
       topics, emotion, content_level, speaker_role
    2. LLM (opcional, ~$0.001/chunk): extrae entities y relationships al
       estilo LightRAG y las persiste en metadata JSONB

    El modo LLM se activa solo si:
        - config.ENABLE_ENTITY_EXTRACTION = true (nuevo flag)
        - El budget guard permite gastar (~$0.002 por chunk es el threshold)
        - El texto tiene más de 50 palabras (no vale la pena en textos cortos)

    Si el LLM falla o el budget está agotado, el sistema continúa sin errores
    con un array vacío en entities y relationships.
    """

    def classify(
        self,
        content: str,
        filename: str = "",
        extra: Optional[dict] = None,
    ) -> ChunkMetadata:
        """
        Clasificación programática síncrona (sin LLM).
        Llama a enrich_with_entities() separadamente si querés el enriquecimiento.
        """
        content_lower = content.lower()
        filename_lower = filename.lower()

        metadata = ChunkMetadata(
            source_type=self._detect_source_type(filename_lower, content_lower),
            speaker_role=self._detect_speaker_role(filename_lower, content_lower),
            topics=self._extract_topics(content_lower),
            content_level=self._estimate_content_level(content_lower),
            emotion=self._detect_emotion(content_lower),
            domain=self._detect_domain(content_lower),
        )

        if extra:
            metadata.edition   = extra.get("edition")
            metadata.alumno_id = extra.get("alumno_id")
            metadata.fecha     = extra.get("fecha")

        return metadata

    async def classify_and_enrich(
        self,
        content: str,
        filename: str = "",
        extra: Optional[dict] = None,
    ) -> ChunkMetadata:
        """
        Punto de entrada principal para la ingesta.
        Combina clasificación por keywords + extracción de entidades por LLM.

        Si la extracción LLM falla o está deshabilitada, retorna la metadata
        de keywords igualmente (nunca bloquea la ingesta).
        """
        # 1. Clasificación por keywords (siempre)
        metadata = self.classify(content, filename, extra)

        # 2. Enriquecimiento con entidades (si está habilitado y hay texto suficiente)
        word_count = len(content.split())
        if word_count < 50:
            logger.debug("Skipping entity extraction: text too short (%d words)", word_count)
            return metadata

        try:
            entities, relationships = await self.enrich_with_entities(content)
            metadata.entities = entities
            metadata.relationships = relationships
        except Exception as e:
            logger.warning(
                "Entity extraction failed for '%s': %s. Continuing without entities.",
                filename, e
            )

        return metadata

    async def enrich_with_entities(
        self,
        text: str,
    ) -> tuple[list[dict], list[dict]]:
        """
        Extrae entidades y relaciones del texto usando LLM (estilo LightRAG).

        Returns:
            (entities, relationships) donde cada uno es una lista de dicts.
            Retorna ([], []) si el LLM falla, el budget está agotado, o la
            extracción está deshabilitada.

        Costo estimado: ~$0.001 por chunk con gpt-4.1-mini
        En Ollama: $0 (sin costo real)
        """
        from poc.config import config
        from poc.budget_guard import check_budget_and_warn, get_active_model

        # Verificar si la extracción está habilitada
        if not getattr(config, 'ENABLE_ENTITY_EXTRACTION', True):
            return [], []

        # No gastar presupuesto en LLM si estamos en critical (>90%)
        budget_status = check_budget_and_warn()
        if budget_status == "critical":
            logger.debug("Entity extraction skipped: budget critical")
            return [], []

        model = get_active_model()
        prompt = _ENTITY_EXTRACTION_PROMPT.format(
            text=text[:2000]  # Limitar a 2000 chars para controlar costo
        )

        try:
            from agent.custom_openai_client import OptimizedOpenAIClient
            client = OptimizedOpenAIClient(model=model, temperature=0.0)
            content, usage = await client.complete(
                prompt=prompt,
                response_format={"type": "json_object"},
            )

            # Registrar costo
            from poc.budget_guard import record_cost
            record_cost(model, usage.prompt_tokens, usage.completion_tokens)

            # Parsear respuesta
            result_dict = client.parse_json_response(content)
            if not result_dict:
                return [], []

            # Validar con Pydantic
            result = EntityExtractionResult(**result_dict)

            entities = [e.model_dump() for e in result.entities]
            relationships = [r.model_dump() for r in result.relationships]

            logger.debug(
                "Entity extraction: %d entities, %d relationships (tokens: %d)",
                len(entities), len(relationships), usage.total_tokens
            )
            return entities, relationships

        except Exception as e:
            logger.warning("LLM entity extraction failed: %s", e)
            return [], []

    # =========================================================================
    # MÉTODOS DE CLASIFICACIÓN POR KEYWORDS (sin LLM)
    # =========================================================================

    def _detect_source_type(self, filename: str, content: str) -> str:
        for source_type, patterns in SOURCE_TYPE_PATTERNS.items():
            for p in patterns:
                if p in filename:
                    return source_type
        content_start = content[:200]
        for source_type, patterns in SOURCE_TYPE_PATTERNS.items():
            for p in patterns:
                if p in content_start:
                    return source_type
        return "otro"

    def _detect_speaker_role(self, filename: str, content: str) -> str:
        for role, patterns in SPEAKER_ROLE_PATTERNS.items():
            for p in patterns:
                if p in filename or p in content[:300]:
                    return role
        return "desconocido"

    def _extract_topics(self, content: str) -> list[str]:
        found = []
        for topic, keywords in TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw in content:
                    found.append(topic)
                    break
        return found[:5]

    def _estimate_content_level(self, content: str) -> int:
        advanced_count = sum(1 for v in ADVANCED_VOCABULARY if v in content)
        basic_count    = sum(1 for v in BASIC_VOCABULARY if v in content)
        word_count     = len(content.split())
        if advanced_count >= 5:
            return 4
        if advanced_count >= 2:
            return 3
        if basic_count >= 2 or word_count < 100:
            return 1
        return 2

    def _detect_emotion(self, content: str) -> str:
        scores: dict[str, int] = {}
        for emotion, keywords in EMOTION_KEYWORDS.items():
            if not keywords:
                continue
            scores[emotion] = sum(1 for kw in keywords if kw in content)
        if not scores or max(scores.values()) == 0:
            return "neutral"
        priority = ["win", "motivacion", "frustracion", "miedo"]
        max_score = max(scores.values())
        for emotion in priority:
            if scores.get(emotion, 0) == max_score:
                return emotion
        return max(scores, key=scores.get)  # type: ignore

    def _detect_domain(self, content: str) -> str:
        scores: dict[str, int] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in content)
        if max(scores.values()) == 0:
            return "metodologia"
        return max(scores, key=scores.get)  # type: ignore

    # =========================================================================
    # BÚSQUEDA DE ENTIDADES (para usar en tools.py)
    # =========================================================================

    @staticmethod
    def find_entity_names(metadata: dict) -> list[str]:
        """Extrae nombres de entidades de la metadata de un chunk."""
        return [e.get("name", "") for e in metadata.get("entities", [])]

    @staticmethod
    def entities_overlap(
        metadata_a: dict,
        metadata_b: dict,
    ) -> list[str]:
        """
        Retorna las entidades que comparten dos chunks.
        Útil para detectar diversidad: si dos chunks tienen muchas entidades
        en común, probablemente hablan de lo mismo.
        """
        names_a = set(e.get("name", "").lower() for e in metadata_a.get("entities", []))
        names_b = set(e.get("name", "").lower() for e in metadata_b.get("entities", []))
        return list(names_a & names_b)


# =============================================================================
# EJEMPLO DE USO
# =============================================================================
if __name__ == "__main__":
    import asyncio
    import json as json_module

    sample = """
    En esta llamada de ventas, Juan estaba muy nervioso porque el cliente 
    dijo que era muy caro. Trabajamos la objeción de pricing y al final 
    cerré el deal. El cliente era una empresa B2B de 50 empleados.
    Usamos la metodología de discovery call que aprendimos en la masterclass.
    La clave fue identificar el sesgo de confirmación del cliente y redirigir
    la conversación hacia el retorno de inversión.
    """

    tm = TaxonomyManager()

    async def demo():
        result = await tm.classify_and_enrich(
            content=sample,
            filename="llamada_venta_juan_sesion14.md",
            extra={"edition": 14, "alumno_id": "juan-garcia"},
        )
        print(json_module.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    asyncio.run(demo())