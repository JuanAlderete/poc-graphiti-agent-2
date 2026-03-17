import pytest
from poc.agents.registry import get_agent, list_formats
from poc.agents.base_agent import AgentInput, ContentPiece
from unittest.mock import AsyncMock, patch, MagicMock

def test_registry_contains_formats():
    formats = list_formats()
    assert "reel_cta" in formats
    assert "ads" in formats

def test_agent_inputs_json_mapping():
    """
    Test extra_validations over an empty dictionary return expected structured errors
    verifying exactly the Notion properties validation loop handles properly over inherited format.
    """
    agent = get_agent("ads")
    input_data = AgentInput(topic="Ventas")
    errors = agent._extra_validations({}, input_data)
    
    assert len(errors) > 0
    assert any("copy" in err for err in errors)
    assert any("headlines" in err for err in errors)
    
def test_historia_agent_validations():
    agent = get_agent("historia")
    input_data = AgentInput(topic="Test")
    errors = agent._extra_validations({"cta_final": "Comprar"}, input_data)
    
    assert len(errors) > 0 
    assert len(errors) > 0 
    assert any("slides" in err for err in errors)

def test_reel_cta_parse_response_tolerant():
    """_parse_response debe manejar JSON envuelto en markdown (Ollama)."""
    agent = get_agent("reel_cta")
    # Simular respuesta de Ollama con backticks
    raw = '```json\n{"hook": "Test hook", "script": "Test", "cta": "Seguir", "sugerencias_grabacion": "", "copy": ""}\n```'
    result = agent._parse_response(raw)
    assert result["hook"] == "Test hook"
    assert result["cta"] == "Seguir"

def test_email_parse_response_direct_json():
    """_parse_response debe manejar JSON directo correctamente."""
    agent = get_agent("email")
    raw = '{"asunto": "Test", "preheader": "Pre", "cuerpo": "Body", "cta": "Click", "ps": ""}'
    result = agent._parse_response(raw)
    assert result["asunto"] == "Test"
    assert result["cta"] == "Click"

@pytest.mark.asyncio
async def test_generate_dry_run_with_mock():
    """generate() con LLM mockeado debe retornar ContentPiece con qa_passed."""
    from poc.agents.base_agent import AgentInput, ContentPiece
    
    agent = get_agent("email")
    mock_response = '{"asunto": "Test asunto", "preheader": "Pre", "cuerpo": "Cuerpo largo para pasar QA", "cta": "Seguir", "ps": ""}'
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50
    
    with patch.object(agent.client, "complete", new=AsyncMock(return_value=(mock_response, mock_usage))):
        piece = await agent.generate(AgentInput(topic="Test"))
        assert isinstance(piece, ContentPiece)
        assert piece.qa_passed is True
        assert piece.content["asunto"] == "Test asunto"
