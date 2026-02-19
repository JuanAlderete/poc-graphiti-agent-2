TEST_QUERIES = [
    # Vector-heavy
    {"id": 1, "text": "¿Cuáles son las estrategias de valoración de startups en 2024?", "type": "vector"},
    {"id": 2, "text": "Explica el concepto de Product Market Fit según los documentos.", "type": "vector"},
    {"id": 3, "text": "¿Qué roles son clave en un equipo de ingeniería inicial?", "type": "vector"},
    {"id": 4, "text": "Diferencias entre Seed y Series A.", "type": "vector"},
    {"id": 5, "text": "¿Cómo afecta la inflación a las rondas de inversión?", "type": "vector"},

    # Graph-heavy (Entities & Relations)
    {"id": 6, "text": "¿Qué relación existe entre OpenAI y Microsoft?", "type": "graph"},
    {"id": 7, "text": "¿Quiénes son los inversores principales mencionados?", "type": "graph"},
    {"id": 8, "text": "¿Qué empresas ha fundado Elon Musk según el texto?", "type": "graph"},
    {"id": 9, "text": "¿Cómo se conectan los conceptos de IA y Ética?", "type": "graph"},
    {"id": 10, "text": "Lista las adquisiciones mencionadas en el sector tecnológico.", "type": "graph"},

    # Hybrid
    {"id": 11, "text": "Analiza el impacto de la IA generativa en el mercado laboral comparando opiniones.", "type": "hybrid"},
    {"id": 12, "text": "Resumen de las tendencias de capital de riesgo y sus principales actores.", "type": "hybrid"},
    {"id": 13, "text": "Dame un perfil de Sam Altman y sus conexiones.", "type": "hybrid"},
    {"id": 14, "text": "Estrategias de crecimiento vs rentabilidad en SaaS.", "type": "hybrid"},
    {"id": 15, "text": "Historia de la evolución de los LLMs.", "type": "hybrid"},

    # Mixed/Edge cases
    {"id": 16, "text": "Dime todo sobre 'Quantum Computing' si existe.", "type": "vector"},
    {"id": 17, "text": "Relaciones de competidores de Google.", "type": "graph"},
    {"id": 18, "text": "Impacto regulatorio en Europa.", "type": "hybrid"},
    {"id": 19, "text": "¿Qué dijo Satya Nadella sobre el futuro?", "type": "vector"},
    {"id": 20, "text": "Conexiones entre Nvidia y el mercado de chips.", "type": "graph"},
]
