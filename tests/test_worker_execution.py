import pytest
from uuid import uuid4

from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService
from app.worker.execution_worker import Worker
from app.schemas.task import TaskCreateRequest


def test_successful_execution(db_session):
    repo = TaskRepository(db_session)
    service = TaskService(repo)
    
    # Create a task
    task_data = TaskCreateRequest(title="Test Task", description="This should succeed", project_id=uuid4(), priority="high")
    task = service.create(task_data)
    
    assert task.status == "Draft"
    
    # Manually set status to queued for the test
    task_db = repo.get(task.id)
    task_db.status = "queued"
    db_session.commit()
    
    # Execute the task using the worker
    worker = Worker(repo)
    success = worker.run_once()
    
    assert success is True
    
    # Verify task status
    updated_task = service.get(task.id)
    assert updated_task.status == "completed"
    assert updated_task.completed_at is not None
    assert updated_task.error is None


def test_failed_execution(db_session):
    repo = TaskRepository(db_session)
    service = TaskService(repo)
    
    # Create a task that will fail
    task_data = TaskCreateRequest(title="Failing Task", description="This task will fail", project_id=uuid4(), priority="high")
    task = service.create(task_data)
    
    assert task.status == "Draft"
    
    # Manually set status to queued for the test
    task_db = repo.get(task.id)
    task_db.status = "queued"
    db_session.commit()
    
    # Execute the task using the worker
    worker = Worker(repo)
    success = worker.run_once()
    
    assert success is False
    
    # Verify task status
    updated_task = service.get(task.id)
    assert updated_task.status == "failed"
    assert updated_task.completed_at is not None
    assert "Simulated execution failure" in updated_task.error


def test_task_claiming(db_session):
    repo = TaskRepository(db_session)
    service = TaskService(repo)
    
    # Create multiple tasks
    task1 = service.create(TaskCreateRequest(title="Task 1", description="First", project_id=uuid4(), priority="high"))
    task2 = service.create(TaskCreateRequest(title="Task 2", description="Second", project_id=uuid4(), priority="high"))
    
    # Manually set status to queued for the test
    for task in [task1, task2]:
        task_db = repo.get(task.id)
        task_db.status = "queued"
    db_session.commit()
    
    # Claim a task
    claimed_task = service.claim_task()
    
    assert claimed_task is not None
    assert claimed_task.status == "executing"
    
    # Verify the claimed task is one of the created ones
    claimed_id = claimed_task.id
    assert claimed_id in [task1.id, task2.id]
    
    # Verify the task in the DB is now executing
    db_task = service.get(claimed_id)
    assert db_task.status == "executing"
    assert db_task.worker_id is not None


def test_protection_against_duplicate_claiming(db_session):
    repo = TaskRepository(db_session)
    service = TaskService(repo)
    
    # Create a task
    task = service.create(TaskCreateRequest(title="Single Task", description="Only one", project_id=uuid4(), priority="high"))
    
    # Manually set status to queued for the test
    task_db = repo.get(task.id)
    task_db.status = "queued"
    db_session.commit()
    
    # First worker claims the task
    claimed_task_1 = service.claim_task()
    assert claimed_task_1 is not None
    
    # Second worker tries to claim a task
    claimed_task_2 = service.claim_task()
    
    # There should be no more tasks to claim
    assert claimed_task_2 is None
    
    # Verify the task is still claimed by the first worker
    db_task = service.get(task.id)
    assert db_task.status == "executing"
    assert claimed_task_1.id == task.id


def test_correct_final_task_status(db_session):
    repo = TaskRepository(db_session)
    service = TaskService(repo)
    
    # Test completion
    task1 = service.create(TaskCreateRequest(title="Complete Me", description="Success", project_id=uuid4(), priority="high"))
    task_db = repo.get(task1.id)
    task_db.status = "queued"
    db_session.commit()
    
    worker = Worker(repo)
    worker.run_once()
    
    assert service.get(task1.id).status == "completed"
    
    # Test failure
    task2 = service.create(TaskCreateRequest(title="Fail Me", description="fail", project_id=uuid4(), priority="high"))
    task_db = repo.get(task2.id)
    task_db.status = "queued"
    db_session.commit()
    
    worker.run_once()
    
    assert service.get(task2.id).status == "failed"
