import argparse
import sys


def queue_status() -> dict:
    from app import app
    from queue_utils import get_queue_diagnostics

    with app.app_context():
        return get_queue_diagnostics()


def print_status() -> None:
    status = queue_status()
    print(f"Redis ping: {bool(status.get('redis_reachable'))}")
    print(f"Redis URL: {status.get('redis_url')}")
    print(f"Queue name: {status.get('queue_name')}")
    print(f"Queued jobs: {status.get('queued_job_count', 0)}")
    print(f"Started jobs: {status.get('started_job_count', 0)}")
    print(f"Failed jobs: {status.get('failed_job_count', 0)}")
    print(f"Finished jobs: {status.get('finished_job_count', 0)}")
    print(f"Scheduled jobs: {status.get('scheduled_job_count', 0)}")
    print(f"Worker count: {status.get('worker_count', 0)}")
    print(status.get("message") or "")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the deployment RQ queue without exposing secrets.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show Redis/RQ queue status.")
    args = parser.parse_args(argv)

    if args.command == "status":
        print_status()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
