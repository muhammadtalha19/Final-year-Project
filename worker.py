import os

from queue_utils import QUEUE_NAME, mask_redis_url


listen = [QUEUE_NAME]


def _flag(name: str) -> str:
    return os.getenv(name, "false")


if __name__ == "__main__":
    from redis import Redis
    from rq import Queue, Worker
    from tasks import run_deployment_job

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    print("Starting deployment worker")
    print(f"FLASK_ENV={os.getenv('FLASK_ENV', 'development')}")
    print(f"REDIS_URL={mask_redis_url(redis_url)}")
    print(f"Listening queues={', '.join(listen)}")
    print(
        "Real deployment flags: "
        f"ENABLE_REAL_DEPLOYMENT={_flag('ENABLE_REAL_DEPLOYMENT')}, "
        f"ALLOW_AWS_DEPLOYMENT={_flag('ALLOW_AWS_DEPLOYMENT')}, "
        f"ALLOW_AZURE_DEPLOYMENT={_flag('ALLOW_AZURE_DEPLOYMENT')}, "
        f"ALLOW_GCP_DEPLOYMENT={_flag('ALLOW_GCP_DEPLOYMENT')}"
    )
    print("Keep this worker running for real deployments.")
    print(f"Task import check=ok ({run_deployment_job.__name__})")

    redis_conn = Redis.from_url(redis_url)
    worker = Worker([Queue(name, connection=redis_conn) for name in listen], connection=redis_conn)
    worker.work()
