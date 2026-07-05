from app.repositories.execution_repository import repository

class PersistenceService:
    def persist(self, goal, status):
        repository.save({"goal":goal,"status":status})

persistence=PersistenceService()
