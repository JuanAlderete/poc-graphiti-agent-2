import asyncio
import logging
from pathlib import Path
from typing import Optional

from graphiti_core.nodes import EpisodeType

from agent.config import settings
from agent.custom_openai_client import OptimizedOpenAIClient
from agent.graph_utils import GraphManager

logger = logging.getLogger(__name__)

# Directorio de documentos
DOCS_DIR = Path(__file__).parent.parent / "documents_to_index"

# Usar un group_id consistente para todos los episodios
# o None si quieres que estén disponibles globalmente
DEFAULT_GROUP_ID = "hybrid_rag_documents"  # <-- Todos los docs en el mismo grupo


async def hydrate_graph(
    graph_manager: GraphManager,
    group_id: Optional[str] = DEFAULT_GROUP_ID,  # <-- PASAR EL GROUP_ID
):
    """
    Read all markdown files and add them as episodes to the graph.
    """
    if not DOCS_DIR.exists():
        logger.error(f"Documents directory not found: {DOCS_DIR}")
        return
    
    # Obtener todos los archivos .md
    md_files = list(DOCS_DIR.glob("*.md"))
    logger.info(f"Found {len(md_files)} markdown files to process")
    
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
            doc_name = md_file.stem  # nombre sin extensión
            
            logger.info(f"Processing document: {doc_name}")
            
            # Agregar episodio con group_id consistente
            episode_uuid = await graph_manager.add_episode(
                content=content,
                name=doc_name,
                episode_type=EpisodeType.TEXT,
                group_id=group_id,  # <-- USAR EL MISMO GROUP_ID
                source_description=f"Document from {md_file.name}",
            )
            
            logger.info(f"Successfully added episode: {doc_name} (UUID: {episode_uuid})")
            
            # Pequeña pausa entre episodios para no saturar la API
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error processing {md_file.name}: {e}")
            continue
    
    logger.info("Graph hydration completed")


async def verify_episodes(graph_manager: GraphManager):
    """
    Verify that all episodes were added correctly.
    """
    # Buscar TODOS los episodios (group_ids=None)
    all_episodes = await graph_manager.get_all_episodes(group_ids=None)
    
    logger.info(f"Total episodes in graph: {len(all_episodes)}")
    
    for ep in all_episodes:
        logger.info(f"  - {ep['name']} (group: {ep.get('group_id', 'N/A')})")
    
    return all_episodes


async def main():
    """Main entry point."""
    # Inicializar cliente OpenAI optimizado
    openai_client = OptimizedOpenAIClient(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL or "gpt-5-mini",
    )
    await openai_client.setup()
    
    # Inicializar GraphManager
    graph_manager = GraphManager(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
        openai_client=openai_client,
    )
    await graph_manager.initialize()
    
    try:
        # Hidratar el grafo
        await hydrate_graph(graph_manager, group_id=DEFAULT_GROUP_ID)
        
        # Verificar que todos los episodios están ahí
        episodes = await verify_episodes(graph_manager)
        
        logger.info(f"\nVerification complete: {len(episodes)} episodes in graph")
        
    finally:
        await graph_manager.close()
        await openai_client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())