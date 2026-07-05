
from datetime import datetime

class ExecutionHistory:
    def __init__(self):
        self._runs=[]

    def add(self, goal:str, status:str):
        self._runs.append({
            "goal": goal,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        })

    def all(self):
        return list(self._runs)

history = ExecutionHistory()
