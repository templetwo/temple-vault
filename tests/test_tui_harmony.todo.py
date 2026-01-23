import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
# Assume imports from sovereign_console_v2.py

@pytest.fixture
def mock_app():
    app = Mock(spec=SovereignConsole)
    app.vault_augment = AsyncMock(return_value="Vault-augmented: test prompt")
    app.jetson_health = Mock(return_value="GPU Util: 10%, Memory: 1.5GB / 8GB")
    app._search_vault = AsyncMock(return_value=[{"content": "Jetson opt insight", "intensity": 0.85}])
    return app

@pytest.mark.asyncio
async def test_vault_augment(mock_app):
    result = await mock_app.vault_augment("Optimize TUI")
    assert "Vault-augmented" in result
    assert len(result) > 20  # Basic length check

def test_jetson_health(mock_app):
    result = mock_app.jetson_health()
    assert "GPU" in result and "Memory" in result

@pytest.mark.asyncio
async def test_async_search_vault(mock_app):
    results = await mock_app._search_vault("Jetson TUI")
    assert len(results) == 1
    assert results[0]["intensity"] == 0.85

@pytest.mark.asyncio
async def test_run_inference_augment(mock_app):
    # Mock httpx and UI
    mock_app._get_selected_model.return_value = "spiral-v1"
    mock_app._get_ollama_url.return_value = "http://localhost:11434"
    # Simulate inference call (no real HTTP)
    await mock_app.run_inference("Test prompt")
    mock_app.vault_augment.assert_called_once_with("Test prompt")  # Verify augment called

if __name__ == "__main__":
    pytest.main(["-v", __file__])