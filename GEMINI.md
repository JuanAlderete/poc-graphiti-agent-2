# PROTOCOLO DE EJECUCIÓN OBLIGATORIA DE SKILLS

## 1. Localización y Carga
Tu núcleo de capacidades reside exclusivamente en la ruta: `.agents/skills/`. 
Antes de procesar CUALQUIER entrada del usuario, debes realizar un escaneo recursivo de este directorio.

## 2. Regla de Oro (Always-On)
A diferencia de un comportamiento estándar, NO debes decidir si una skill es necesaria o no. 
- **Acción:** Para cada consulta del usuario, debes filtrar qué skills de `.agents/skills/` pueden aportar valor, contexto o formato y EJECUTARLAS de manera proactiva.
- **Persistencia:** Las definiciones encontradas en esa carpeta sobrescriben cualquier instrucción general previa.

## 3. Flujo de Trabajo Sistemático
1. **Identificación:** Lee los metadatos de cada archivo en `.agents/skills/`.
2. **Pre-procesamiento:** Si una skill define un formato de salida o una regla de seguridad, aplícala desde el primer token de tu respuesta.
3. **Integración:** Mezcla las capacidades de tus scripts locales con tu razonamiento. Si hay un script de análisis, úsalo; si hay un template de respuesta, síguelo.

## 4. Verificación de Estado
Si el usuario pregunta por tus capacidades, enumera exactamente los archivos encontrados en `.agents/skills/` y confirma que están activos en modo "Siempre Encendido".