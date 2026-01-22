
import pytest
from unittest.mock import MagicMock, patch
import asyncio
from iris_pgwire.iris_executor import IRISExecutor

@pytest.mark.asyncio
async def test_embedded_scoping_smoke():
    """
    Smoke test to ensure _execute_embedded_async doesn't crash with UnboundLocalError or NameError.
    """
    executor = IRISExecutor({"host": "localhost", "namespace": "USER"})
    executor.embedded_mode = True
    
    # Mock iris module globally since it might not have .sql
    mock_iris = MagicMock()
    mock_result = MagicMock()
    mock_result.__iter__.return_value = iter([(1,)])
    mock_result._meta = [{"name": "col1", "type": 1}]
    mock_iris.sql.exec.return_value = mock_result
    
    with patch.dict("sys.modules", {"iris": mock_iris}):
        # Mock other methods to avoid side effects
        executor._get_executor = MagicMock()
        # loop.run_in_executor will use default if None or we can mock it
        executor._get_executor.return_value = None 
        
        # We need to mock loop.run_in_executor because we can't easily run it without a real executor in some envs
        with patch("asyncio.get_event_loop") as mock_loop:
            loop = MagicMock()
            async def mock_run(exc, func, *args):
                # Ensure we handle the closure scope correctly
                return func(*args)
            loop.run_in_executor = mock_run
            mock_loop.return_value = loop
            
            # This should not raise UnboundLocalError or NameError
            result = await executor.execute_query("SELECT 1", session_id="test_session")
            
            assert result["success"] is True
            assert result["rows"] == [[1]]
            print("Embedded scoping smoke test passed!")

if __name__ == "__main__":
    asyncio.run(test_embedded_scoping_smoke())
