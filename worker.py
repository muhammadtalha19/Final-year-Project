import os

from redis import Redis
from rq import Worker, Queue


listen = ["deployments"]


if __name__ == "__main__":
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_conn = Redis.from_url(redis_url)
    worker = Worker([Queue(name, connection=redis_conn) for name in listen], connection=redis_conn)
    worker.work()
