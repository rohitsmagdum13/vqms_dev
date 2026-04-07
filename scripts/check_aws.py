# ruff: noqa: E402
"""Check connectivity to all AWS services used by VQMS.

Tests S3 buckets, SQS queues, and EventBridge bus reachability.
Reports status for each resource with clear PASS/FAIL indicators.

Usage:
  uv run python scripts/check_aws.py
"""

from __future__ import annotations

import sys
import time

# ---------------------------------------------------------------------------
# Bootstrap -- must happen before project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import boto3
from botocore.exceptions import ClientError

from config.settings import get_settings

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"
HEADER = "\033[1m"
RESET = "\033[0m"


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{HEADER}{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}{RESET}")


def print_check(name: str, passed: bool, detail: str) -> None:
    """Print a single check result."""
    status = PASS if passed else FAIL
    print(f"  {status} {name}")
    print(f"         {detail}")


def print_warn(name: str, detail: str) -> None:
    """Print a warning result."""
    print(f"  {WARN} {name}")
    print(f"         {detail}")


# ---------------------------------------------------------------------------
# S3 checks
# ---------------------------------------------------------------------------

def check_s3(s3_client, bucket_name: str) -> bool:
    """Check if an S3 bucket is accessible.

    Verifies the bucket exists and we have permission to access it.
    Also checks if we can list objects (read access).
    """
    try:
        s3_client.head_bucket(Bucket=bucket_name)

        # Try listing objects to verify read permission
        response = s3_client.list_objects_v2(
            Bucket=bucket_name, MaxKeys=1
        )
        object_count = response.get("KeyCount", 0)
        is_empty = " (empty)" if object_count == 0 else f" ({object_count}+ objects)"

        print_check(
            f"S3: {bucket_name}",
            True,
            f"Bucket accessible, read OK{is_empty}",
        )
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code == "404":
            print_check(
                f"S3: {bucket_name}",
                False,
                "Bucket does NOT exist. Create it with: "
                f"aws s3 mb s3://{bucket_name}",
            )
        elif error_code in ("403", "AccessDenied"):
            print_check(
                f"S3: {bucket_name}",
                False,
                "Access denied — check IAM permissions for s3:HeadBucket "
                "and s3:ListBucket",
            )
        else:
            print_check(
                f"S3: {bucket_name}",
                False,
                f"Error: {error_code} — {e.response['Error']['Message']}",
            )
        return False

    except Exception as e:
        print_check(f"S3: {bucket_name}", False, f"Unexpected error: {e}")
        return False


def check_s3_write(s3_client, bucket_name: str) -> bool:
    """Check if we can write to an S3 bucket.

    Uploads a tiny test object and then deletes it.
    """
    test_key = "_vqms_connectivity_test.txt"
    test_content = b"VQMS connectivity check"

    try:
        s3_client.put_object(
            Bucket=bucket_name, Key=test_key, Body=test_content
        )
        # Clean up the test object
        s3_client.delete_object(Bucket=bucket_name, Key=test_key)

        print_check(
            f"S3 write: {bucket_name}",
            True,
            "Write + delete OK",
        )
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        print_check(
            f"S3 write: {bucket_name}",
            False,
            f"Cannot write — {error_code}: {e.response['Error']['Message']}",
        )
        return False

    except Exception as e:
        print_check(f"S3 write: {bucket_name}", False, f"Unexpected: {e}")
        return False


# ---------------------------------------------------------------------------
# SQS checks
# ---------------------------------------------------------------------------

def check_sqs(sqs_client, queue_name: str) -> bool:
    """Check if an SQS queue exists and is accessible.

    Verifies the queue URL can be resolved and attributes can be read.
    """
    try:
        response = sqs_client.get_queue_url(QueueName=queue_name)
        queue_url = response["QueueUrl"]

        # Get queue attributes to verify read access
        attrs = sqs_client.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )
        visible = attrs["Attributes"].get(
            "ApproximateNumberOfMessages", "?"
        )
        in_flight = attrs["Attributes"].get(
            "ApproximateNumberOfMessagesNotVisible", "?"
        )

        print_check(
            f"SQS: {queue_name}",
            True,
            f"Queue found — {visible} visible, {in_flight} in-flight",
        )
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code == "AWS.SimpleQueueService.NonExistentQueue":
            print_check(
                f"SQS: {queue_name}",
                False,
                "Queue does NOT exist. Create it with: "
                f"aws sqs create-queue --queue-name {queue_name}",
            )
        elif error_code in ("AccessDenied", "AccessDeniedException"):
            print_check(
                f"SQS: {queue_name}",
                False,
                "Access denied — check IAM permissions for "
                "sqs:GetQueueUrl and sqs:GetQueueAttributes",
            )
        else:
            print_check(
                f"SQS: {queue_name}",
                False,
                f"Error: {error_code} — {e.response['Error']['Message']}",
            )
        return False

    except Exception as e:
        print_check(f"SQS: {queue_name}", False, f"Unexpected: {e}")
        return False


# ---------------------------------------------------------------------------
# EventBridge checks
# ---------------------------------------------------------------------------

def check_eventbridge(eb_client, bus_name: str) -> bool:
    """Check if an EventBridge event bus exists and is accessible."""
    try:
        response = eb_client.describe_event_bus(Name=bus_name)
        arn = response.get("Arn", "unknown")

        print_check(
            f"EventBridge: {bus_name}",
            True,
            f"Bus found — ARN: {arn}",
        )
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code == "ResourceNotFoundException":
            print_check(
                f"EventBridge: {bus_name}",
                False,
                "Bus does NOT exist. Create it with: "
                f"aws events create-event-bus --name {bus_name}",
            )
        elif error_code in ("AccessDenied", "AccessDeniedException"):
            print_check(
                f"EventBridge: {bus_name}",
                False,
                "Access denied — check IAM permissions for "
                "events:DescribeEventBus",
            )
        else:
            print_check(
                f"EventBridge: {bus_name}",
                False,
                f"Error: {error_code} — {e.response['Error']['Message']}",
            )
        return False

    except Exception as e:
        print_check(f"EventBridge: {bus_name}", False, f"Unexpected: {e}")
        return False


def check_eventbridge_put(eb_client, bus_name: str, source: str) -> bool:
    """Check if we can publish events to EventBridge.

    Sends a test event with a harmless detail-type that no rule
    will match, so it won't trigger any downstream processing.
    """
    try:
        response = eb_client.put_events(
            Entries=[
                {
                    "Source": source,
                    "DetailType": "VQMSConnectivityTest",
                    "Detail": '{"test": true}',
                    "EventBusName": bus_name,
                }
            ]
        )

        failed_count = response.get("FailedEntryCount", 0)
        if failed_count == 0:
            event_id = response["Entries"][0].get("EventId", "unknown")
            print_check(
                f"EventBridge publish: {bus_name}",
                True,
                f"Event published OK — EventId: {event_id}",
            )
            return True
        else:
            error = response["Entries"][0].get("ErrorMessage", "unknown")
            print_check(
                f"EventBridge publish: {bus_name}",
                False,
                f"Publish failed — {error}",
            )
            return False

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        print_check(
            f"EventBridge publish: {bus_name}",
            False,
            f"Cannot publish — {error_code}: {e.response['Error']['Message']}",
        )
        return False

    except Exception as e:
        print_check(
            f"EventBridge publish: {bus_name}", False, f"Unexpected: {e}"
        )
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run all AWS connectivity checks and print a summary."""
    settings = get_settings()
    region = settings.aws_region

    print("\n  VQMS AWS Connectivity Check")
    print(f"  Region: {region}")

    start = time.time()

    # Track results for summary
    results: dict[str, bool] = {}

    # --- AWS credentials check ---
    print_header("AWS Credentials")
    try:
        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        account = identity.get("Account", "unknown")
        arn = identity.get("Arn", "unknown")
        print_check(
            "AWS Credentials",
            True,
            f"Account: {account}, Identity: {arn}",
        )
        results["credentials"] = True
    except Exception as e:
        print_check(
            "AWS Credentials",
            False,
            f"Cannot authenticate — {e}. Check AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY in .env",
        )
        results["credentials"] = False
        # No point continuing if credentials are bad
        print("\n  Cannot proceed without valid AWS credentials.\n")
        return

    # --- S3 Buckets ---
    print_header("S3 Buckets (4 buckets)")

    s3 = boto3.client("s3", region_name=region)

    s3_buckets = [
        ("email_raw", settings.s3_bucket_email_raw),
        ("attachments", settings.s3_bucket_attachments),
        ("audit", settings.s3_bucket_audit_artifacts),
        ("knowledge", settings.s3_bucket_knowledge),
    ]

    for label, bucket in s3_buckets:
        results[f"s3_{label}"] = check_s3(s3, bucket)

    # Write test on the two buckets we actively write to
    print()
    for label, bucket in [s3_buckets[0], s3_buckets[1]]:
        results[f"s3_write_{label}"] = check_s3_write(s3, bucket)

    # --- SQS Queues ---
    print_header("SQS Queues (2 queues + DLQ)")

    sqs = boto3.client("sqs", region_name=region)

    sqs_queues = [
        settings.sqs_email_intake_queue,
        settings.sqs_query_intake_queue,
        "vqms-dlq",
    ]

    for queue in sqs_queues:
        results[f"sqs_{queue}"] = check_sqs(sqs, queue)

    # --- EventBridge ---
    print_header("EventBridge")

    eb = boto3.client("events", region_name=region)

    results["eventbridge"] = check_eventbridge(
        eb, settings.eventbridge_bus_name
    )
    results["eventbridge_publish"] = check_eventbridge_put(
        eb, settings.eventbridge_bus_name, settings.eventbridge_source
    )

    # --- Summary ---
    elapsed = time.time() - start

    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    total = len(results)

    print_header("Summary")
    print(f"  Total checks: {total}")
    print(f"  {PASS} Passed: {passed}")

    if failed > 0:
        print(f"  {FAIL} Failed: {failed}")
        print()
        print("  Failed resources:")
        for name, ok in results.items():
            if not ok:
                print(f"    - {name}")
    else:
        print("\n  All AWS services are reachable and accessible!")

    print(f"\n  Time: {elapsed:.2f}s\n")


if __name__ == "__main__":
    main()
