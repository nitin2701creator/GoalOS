
class ExecutionLog:
    def __init__(self):
        self.entries=[]

    def write(self, message:str):
        self.entries.append(message)

log = ExecutionLog()
