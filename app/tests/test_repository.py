from app.repositories.execution_repository import repository

def test_save():
    repository.save({"goal":"demo"})
    assert len(repository.all())>0
