
from app.kernel.history.execution_history import history

def test_history():
    history.add("Demo","completed")
    assert len(history.all()) >= 1
