
class StatusTracker:
    def __init__(self):
        self._status={}

    def update(self, workflow_id:str, status:str):
        self._status[workflow_id]=status

    def get(self, workflow_id:str):
        return self._status.get(workflow_id,"unknown")

tracker = StatusTracker()
