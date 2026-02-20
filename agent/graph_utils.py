import os
import logging
from typing import Optional, List
from datetime import datetime

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

logger = logging.getLogger(__name__)

class GraphManager:
    """
    Manages Graphiti graph with proper episode retrieval.
    """
    
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        openai_client=None,
    ):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        self.openai_client = openai_client
        
        self._graphiti: Optional[Graphiti] = None
    
    async def initialize(self):
        """Initialize Graphiti connection."""
        self._graphiti = Graphiti(
            uri=self.uri,
            user=self.user,
            password=self.password,
            llm_client=self.openai_client,
        )
        
        # Inicializar esquema si es necesario
        await self._graphiti.build_indices()
        logger.info("Graphiti initialized successfully")
    
    async def close(self):
        """Close connections."""
        if self._graphiti:
            await self._graphiti.close()
    
    async def add_episode(
        self,
        content: str,
        name: str,
        episode_type: EpisodeType = EpisodeType.TEXT,
        group_id: Optional[str] = None,  # <-- PARÁMETRO IMPORTANTE
        source_description: Optional[str] = None,
    ) -> str:
        """
        Add an episode to the graph.
        
        Args:
            content: The episode content
            name: Episode name/identifier
            episode_type: Type of episode (TEXT, JSON, etc.)
            group_id: Group identifier for filtering. Use None for global access.
            source_description: Optional source metadata
        """
        if not self._graphiti:
            raise RuntimeError("Graphiti not initialized. Call initialize() first.")
        
        # Usar un group_id consistente o None para acceso global
        # Si quieres organizar por documento, usa el nombre del documento como group_id
        # Si quieres acceso global a todos los episodios, usa None
        
        episode = await self._graphiti.add_episode(
            name=name,
            episode_body=content,
            source=episode_type,
            source_description=source_description or f"Document: {name}",
            group_id=group_id,  # <-- CRÍTICO: especificar group_id
            created_at=datetime.now(),
        )
        
        logger.info(f"Added episode '{name}' with UUID: {episode.uuid}")
        return episode.uuid
    
    async def get_all_episodes(
        self,
        group_ids: Optional[List[str]] = None,  # <-- PARÁMETRO CRÍTICO
        limit: int = 100,
    ) -> List[dict]:
        """
        Retrieve ALL episodes from the graph.
        
        IMPORTANTE: Si group_ids=None, devuelve episodios de todos los grupos.
        Si group_ids=[...], filtra por esos grupos específicos.
        """
        if not self._graphiti:
            raise RuntimeError("Graphiti not initialized")
        
        try:
            # El método search_episodes de Graphiti requiere group_ids
            # Para obtener TODOS los episodios, pasamos group_ids=None
            # o una lista vacía según la implementación de Graphiti
            
            episodes = await self._graphiti.search_episodes(
                group_ids=group_ids,  # <-- CLAVE: None = todos los grupos
                limit=limit,
            )
            
            logger.info(f"Retrieved {len(episodes)} episodes")
            
            # Convertir a diccionarios serializables
            result = []
            for ep in episodes:
                result.append({
                    "uuid": str(ep.uuid),
                    "name": ep.name,
                    "content": ep.content if hasattr(ep, 'content') else ep.episode_body,
                    "group_id": ep.group_id,
                    "created_at": ep.created_at.isoformat() if ep.created_at else None,
                    "source": ep.source.value if hasattr(ep.source, 'value') else str(ep.source),
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error retrieving episodes: {e}")
            raise
    
    async def search_episodes_by_content(
        self,
        query: str,
        group_ids: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[dict]:
        """
        Search episodes by content similarity.
        """
        if not self._graphiti:
            raise RuntimeError("Graphiti not initialized")
        
        # Usar el método de búsqueda semántica de Graphiti
        results = await self._graphiti.search(
            query=query,
            group_ids=group_ids,  # <-- También aquí
            limit=limit,
        )
        
        return results