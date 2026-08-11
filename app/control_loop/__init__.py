"""GoalOS control loops.

The persisted scheduler worker (``scheduler_worker``) runs in-process and
executes due schedules through the execution runtime. One loop per
process; due runs are claimed atomically in the database so multiple
workers never double-execute.
"""
