"""
Worker execution engine.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


class Worker:
    """GoalOS Worker that claims and executes tasks."""

    def __init__(self, repository: TaskRepository):
        self.repository = repository
        self.service = TaskService(repository)

    def run_once(self, worker_id: Optional[uuid.UUID] = None) -> bool:
        """Claims and executes a single task if available."""
        claimed_task = self.service.claim_task(worker_id)
        if not claimed_task:
            logger.info("No tasks available to claim.")
            return False

        task_id = claimed_task.id
        logger.info(f"Worker claimed task {task_id}. Starting execution...")
        
        success = self.service.execute_task(task_id)
        
        if success:
            logger.info(f"Task {task_id} executed successfully.")
        else:
            logger.error(f"Task {task_id} execution failed.")
            
        return success
