class ExecutionRepository:
    def __init__(self):
        self.records=[]
    def save(self,record):
        self.records.append(record)
    def all(self):
        return list(self.records)

repository=ExecutionRepository()
