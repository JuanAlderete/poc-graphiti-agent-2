import pytest
from storage.notion_client import NotionClient

@pytest.mark.asyncio
async def test_notion_client_initialization_without_token(monkeypatch):
    """
    Test fallback without active notion tokens correctly instantiates 
    without crashing but without AsyncClient.
    """
    from poc.config import config
    monkeypatch.setattr(config, "NOTION_TOKEN", "")
    client = NotionClient(organization_id="mocked_organization_without_token")
    assert client.client is None
    
@pytest.mark.asyncio
async def test_weekly_rules_fallback(monkeypatch):
    """get_weekly_rules retorna lista vacía cuando NOTION_RULES_DB no está configurado."""
    from poc.config import config
    monkeypatch.setattr(config, "NOTION_RULES_DB", "")
    client = NotionClient(organization_id="mock_org")
    rules = await client.get_weekly_rules()
    assert isinstance(rules, list)
    assert len(rules) == 0
