"""Explicit disposable evidence/budget for HTTP-mock adapter tests."""
import asyncio
from pathlib import Path
import tempfile

from collusion.client import APIClient
from collusion.journal import ExecutionBudget


def offline_client(case, *args, **kwargs):
    kwargs.setdefault('budget',ExecutionBudget(32,600))
    client=APIClient(*args,**kwargs)
    directory=tempfile.TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    case.addCleanup(lambda:asyncio.run(client.close()))
    client.bind_episode(Path(directory.name),{'kind':'OFFLINE_HTTP_MOCK_FIXTURE'})
    return client
