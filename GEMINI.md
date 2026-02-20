# PROTOCOLO DE EJECUCIÓN OBLIGATORIA Y GESTIÓN DE CONTEXTO

## 1. Localización y Carga de Skills
Tu núcleo de capacidades reside exclusivamente en la ruta: `./.agents/skills/`. 
- **Acción:** Antes de procesar CUALQUIER entrada, realiza un escaneo recursivo de este directorio.
- **Regla Always-On:** No decidas si una skill es necesaria; ejecútalas de manera proactiva si aportan valor, contexto o formato.

## 2. El README.md como Mapa Maestro
El archivo `README.md` en la raíz es la autoridad máxima del proyecto y consta de 11 secciones críticas.
- **Consulta Obligatoria:** Verifica el `README.md` en cada interacción para asegurar que tu respuesta está alineada con el estado actual del proyecto.
- **Sincronización en Tiempo Real:** Si durante la conversación o ejecución de skills se agrega, elimina o modifica cualquier componente, funcionalidad o archivo, DEBES actualizar la sección correspondiente del `README.md` inmediatamente. No esperes a que el usuario lo pida.

## 3. Flujo de Trabajo Sistemático
1. **Identificación:** Lee metadatos de `./.agents/skills/` y las 11 secciones del `README.md`.
2. **Pre-procesamiento:** Aplica formatos o reglas de seguridad de las skills desde el primer token.
3. **Integración y Mantenimiento:** Mezcla las capacidades locales con tu razonamiento. Si detectas un cambio en la estructura del proyecto, refleja el cambio en el `README.md` para mantener la integridad de las 11 secciones.

## 4. Verificación de Estado
A solicitud del usuario, enumera los archivos en `./.agents/skills/` y confirma que el `README.md` está sincronizado con los últimos cambios realizados.