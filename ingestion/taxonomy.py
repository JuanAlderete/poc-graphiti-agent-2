"""
ingestion/taxonomy.py
---------------------
TaxonomyManager: clasifica chunks y documentos en el momento de la ingesta.

Principio: sin LLM. Solo regex + keywords. Rápido, barato, determinista.
El resultado se escribe en metadata JSONB de chunks y documents en Postgres.

Uso:
    tm = TaxonomyManager()
    metadata = tm.classify(content="...", filename="sesion_14_validacion.md")
    # → {source_type, topics, domain, content_level, emotion, speaker_role}
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional


# =============================================================================
# CONSTANTES DE CLASIFICACIÓN
# =============================================================================

# source_type: detectado principalmente por nombre de archivo o path
SOURCE_TYPE_PATTERNS: dict[str, list[str]] = {
    "llamada_venta":  ["llamada", "venta", "closer", "cierre", "prospecto", "sales_call"],
    "sesion_grupal":  ["sesion", "sesión", "grupal", "grupo", "cohorte", "masterclass", "clase"],
    "podcast":        ["podcast", "episodio", "episode", "ep_", "ep-"],
    "masterclass":    ["masterclass", "master_class", "taller", "workshop"],
    "email":          ["email", "newsletter", "correo"],
    "entrevista":     ["entrevista", "interview"],
}

# domain: clasificado por presencia de keywords en el contenido
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

# topics: lista de temas frecuentes en el dominio Novolabs
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

# emotion: detectado por expresiones emocionales en el texto
EMOTION_KEYWORDS: dict[str, list[str]] = {
    "miedo":       ["miedo", "asustado", "nervioso", "pánico", "terror", "temor", "preocupado"],
    "frustracion": ["frustrado", "frustración", "harto", "cansado", "no funciona", "imposible", "rendirse"],
    "win":         ["éxito", "logré", "funcionó", "increíble", "resultado", "cerré", "gané", "conseguí"],
    "motivacion":  ["motivado", "energía", "ganas", "entusiasmo", "pasión", "inspirado", "creer"],
    "neutral":     [],  # fallback
}

# speaker_role: detectado por patrones en el texto o en el filename
SPEAKER_ROLE_PATTERNS: dict[str, list[str]] = {
    "fundador":  ["fundador", "founder", "ceo", "co-founder", "cofundador"],
    "alumno":    ["alumno", "estudiante", "participante", "cohorte"],
    "mentor":    ["mentor", "coach", "consultor", "advisor"],
    "closer":    ["closer", "vendedor", "sales", "comercial"],
}

# content_level: estimado por vocabulario técnico y longitud
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


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ChunkMetadata:
    """Metadata enriquecida de un chunk, lista para insertar en Postgres."""
    source_type:    str = "otro"
    speaker_role:   str = "desconocido"
    topics:         list[str] = field(default_factory=list)
    content_level:  int = 1          # 1=básico, 2=intermedio, 3=avanzado, 4=experto
    emotion:        str = "neutral"
    domain:         str = "metodologia"
    edition:        Optional[int] = None
    alumno_id:      Optional[str] = None
    fecha:          Optional[str] = None
    used_count:     int = 0
    last_used_at:   None = None
    is_deleted:     bool = False

    def to_dict(self) -> dict:
        return {
            "source_type":   self.source_type,
            "speaker_role":  self.speaker_role,
            "topics":        self.topics,
            "content_level": self.content_level,
            "emotion":       self.emotion,
            "domain":        self.domain,
            "edition":       self.edition,
            "alumno_id":     self.alumno_id,
            "fecha":         self.fecha or date.today().isoformat(),
            "used_count":    self.used_count,
            "last_used_at":  self.last_used_at,
            "is_deleted":    self.is_deleted,
        }


# =============================================================================
# TAXONOMY MANAGER
# =============================================================================

class TaxonomyManager:
    """
    Clasifica documentos y chunks en el momento de la ingesta.
    Sin LLM: solo regex + keywords. Rápido y predecible.

    Responsabilidades:
    - Detectar source_type desde el nombre de archivo
    - Detectar domain desde el contenido
    - Extraer topics desde el contenido
    - Estimar content_level desde vocabulario
    - Detectar emotion dominante
    - Detectar speaker_role

    No responsabilidades:
    - NO hace chunking
    - NO hace embeddings
    - NO llama a la API de OpenAI
    """

    def classify(
        self,
        content: str,
        filename: str = "",
        extra: Optional[dict] = None,
    ) -> ChunkMetadata:
        """
        Punto de entrada principal. Clasifica un chunk o documento.

        Args:
            content:  Texto del chunk o documento completo.
            filename: Nombre del archivo original (ayuda a detectar source_type).
            extra:    Metadata adicional conocida (edition, alumno_id, fecha).

        Returns:
            ChunkMetadata con todos los campos clasificados.
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

        # Incorporar metadata extra si viene desde el pipeline de ingesta
        if extra:
            metadata.edition   = extra.get("edition")
            metadata.alumno_id = extra.get("alumno_id")
            metadata.fecha     = extra.get("fecha")

        return metadata

    # --------------------------------------------------------------------------
    # DETECCIÓN DE SOURCE TYPE
    # --------------------------------------------------------------------------
    def _detect_source_type(self, filename: str, content: str) -> str:
        """Detecta el tipo de fuente desde el nombre de archivo primero, luego contenido."""
        for source_type, patterns in SOURCE_TYPE_PATTERNS.items():
            for p in patterns:
                if p in filename:
                    return source_type

        # Fallback: buscar en las primeras 200 chars del contenido
        content_start = content[:200]
        for source_type, patterns in SOURCE_TYPE_PATTERNS.items():
            for p in patterns:
                if p in content_start:
                    return source_type

        return "otro"

    # --------------------------------------------------------------------------
    # DETECCIÓN DE SPEAKER ROLE
    # --------------------------------------------------------------------------
    def _detect_speaker_role(self, filename: str, content: str) -> str:
        for role, patterns in SPEAKER_ROLE_PATTERNS.items():
            for p in patterns:
                if p in filename or p in content[:300]:
                    return role
        return "desconocido"

    # --------------------------------------------------------------------------
    # EXTRACCIÓN DE TOPICS
    # --------------------------------------------------------------------------
    def _extract_topics(self, content: str) -> list[str]:
        """
        Retorna lista de topics presentes en el contenido.
        Máximo 5 topics para no inflar la metadata.
        """
        found = []
        for topic, keywords in TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw in content:
                    found.append(topic)
                    break  # Solo 1 match por topic es suficiente

        # Ordenar por frecuencia no es necesario con keywords, limitamos a 5
        return found[:5]

    # --------------------------------------------------------------------------
    # ESTIMACIÓN DE CONTENT LEVEL
    # --------------------------------------------------------------------------
    def _estimate_content_level(self, content: str) -> int:
        """
        Estima nivel de contenido:
        1 = básico (introductorio)
        2 = intermedio (conceptos aplicados)
        3 = avanzado (vocabulario técnico)
        4 = experto (jerga de industria, métricas específicas)
        """
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

    # --------------------------------------------------------------------------
    # DETECCIÓN DE EMOCIÓN
    # --------------------------------------------------------------------------
    def _detect_emotion(self, content: str) -> str:
        """
        Retorna la emoción dominante del chunk.
        Si hay empate, prioriza en este orden: win > motivacion > frustracion > miedo > neutral.
        """
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

    # --------------------------------------------------------------------------
    # DETECCIÓN DE DOMAIN
    # --------------------------------------------------------------------------
    def _detect_domain(self, content: str) -> str:
        """
        Retorna el dominio con mayor cantidad de keywords presentes.
        Fallback: metodologia (es el más genérico del stack Novolabs).
        """
        scores: dict[str, int] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in content)

        if max(scores.values()) == 0:
            return "metodologia"

        return max(scores, key=scores.get)  # type: ignore


# =============================================================================
# EJEMPLO DE USO (ejecutar como script para testear)
# =============================================================================
if __name__ == "__main__":
    sample = """
    En esta llamada de ventas, Juan estaba muy nervioso porque el cliente 
    dijo que era muy caro. Trabajamos la objeción de pricing y al final 
    cerré el deal. El cliente era una empresa B2B de 50 empleados.
    Usamos la metodología de discovery call que aprendimos en la masterclass.
    """

    tm = TaxonomyManager()
    result = tm.classify(
        content=sample,
        filename="llamada_venta_juan_sesion14.md",
        extra={"edition": 14, "alumno_id": "juan-garcia"},
    )

    import json
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))