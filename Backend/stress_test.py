"""
stress_test.py — Concurrent load test for AutoHire's /resumes/screen endpoint

Simulates multiple recruiters hitting /resumes/screen at the same time
against one (or more) job_id(s), so we can see how the retry/backoff
logic behaves under real concurrent pressure instead of a single
Swagger click.

Usage:
    python stress_test.py

Edit the CONFIG block below before running.
"""

import time
import statistics
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─────────────────────────── CONFIG ───────────────────────────
BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/resumes/screen"

# Put one or more existing job_ids here. If you only have one, just
# repeat it — the point is to simulate several recruiters screening
# against the same (or different) job(s) at once.
JOB_IDS = [
    1,
    1,
    2,
]

# How many concurrent requests to fire per job_id, per round.
CONCURRENT_REQUESTS = 5   # e.g. 3 job_ids x 5 = 15 concurrent calls

# How many rounds to run (set >1 to hammer it repeatedly).
ROUNDS = 1

# Per-request timeout (seconds). With the shared rate limiter now pacing
# every Groq call to ~25/min across all concurrent requests, a full
# queue of 200+ candidate screenings can genuinely take several minutes
# to drain — this is expected, not a hang.
TIMEOUT = 600
# ────────────────────────────────────────────────────────────────


def screen_job(job_id: int, call_index: int):
    """Fire one POST /resumes/screen call and time it."""
    start = time.perf_counter()
    try:
        resp = requests.post(
            ENDPOINT,
            json={"job_id": str(job_id)},
            timeout=TIMEOUT,
        )
        elapsed = time.perf_counter() - start
        data = None
        try:
            data = resp.json()
        except ValueError:
            pass

        failed_candidates = None
        if isinstance(data, dict):
            failed_candidates = data.get("failed_candidates")

        return {
            "call_index": call_index,
            "job_id": job_id,
            "status_code": resp.status_code,
            "elapsed": elapsed,
            "failed_candidates": failed_candidates,
            "error": None,
            "body": data if resp.status_code != 200 else None,
        }
    except requests.exceptions.RequestException as e:
        elapsed = time.perf_counter() - start
        return {
            "call_index": call_index,
            "job_id": job_id,
            "status_code": None,
            "elapsed": elapsed,
            "failed_candidates": None,
            "error": str(e),
            "body": None,
        }


def run_round(round_num: int):
    print(f"\n=== Round {round_num} ===")
    tasks = []
    for job_id in JOB_IDS:
        for i in range(CONCURRENT_REQUESTS):
            tasks.append((job_id, f"{job_id}-{i}"))

    results = []
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = {
            executor.submit(screen_job, job_id, call_index): call_index
            for job_id, call_index in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = result["status_code"] or "ERROR"
            print(
                f"  call {result['call_index']:>6} | job {result['job_id']} "
                f"| status {status} | {result['elapsed']:.2f}s "
                f"| failed_candidates={result['failed_candidates']}"
            )

    return results


def summarize(all_results):
    print("\n=== Summary ===")
    total = len(all_results)
    successes = [r for r in all_results if r["status_code"] == 200]
    errors = [r for r in all_results if r["status_code"] != 200]

    print(f"Total requests:      {total}")
    print(f"Successful (200):    {len(successes)}")
    print(f"Non-200 / errored:   {len(errors)}")

    if successes:
        times = [r["elapsed"] for r in successes]
        print(f"Avg response time:   {statistics.mean(times):.2f}s")
        print(f"Min / Max:           {min(times):.2f}s / {max(times):.2f}s")

    any_failed_candidates = [
        r for r in successes
        if r["failed_candidates"]  # non-empty list/truthy
    ]
    if any_failed_candidates:
        print(f"\n⚠ {len(any_failed_candidates)} response(s) had non-empty failed_candidates:")
        for r in any_failed_candidates:
            print(f"  call {r['call_index']} (job {r['job_id']}): {r['failed_candidates']}")
    else:
        print("\nNo response reported failed_candidates.")

    if errors:
        print(f"\n⚠ {len(errors)} request(s) errored or returned non-200:")
        for r in errors:
            print(f"  call {r['call_index']} (job {r['job_id']}): "
                  f"status={r['status_code']} error={r['error']} body={r.get('body')}")


if __name__ == "__main__":
    print(f"Hitting {ENDPOINT}")
    print(f"Job IDs: {JOB_IDS} | {CONCURRENT_REQUESTS} concurrent req/job | {ROUNDS} round(s)")

    all_results = []
    for round_num in range(1, ROUNDS + 1):
        all_results.extend(run_round(round_num))

    summarize(all_results)