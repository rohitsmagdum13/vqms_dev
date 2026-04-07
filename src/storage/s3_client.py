"""S3 storage adapter for VQMS.

All file storage goes through real S3 using boto3. No local
filesystem fallback. Pre-provisioned buckets are read from
environment variables via settings.

Corresponds to the 4 S3 buckets in the VQMS architecture:
  - vqms-email-raw-prod (raw .eml files)
  - vqms-email-attachments-prod (attachment files)
  - vqms-audit-artifacts-prod (audit artifacts)
  - vqms-knowledge-artifacts-prod (KB articles, prompt templates)

For testing, use moto to mock S3 calls.
"""

from __future__ import annotations

import logging

import boto3
from botocore.exceptions import ClientError

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Lazy-initialized S3 client (created on first use)
_s3_client = None


def _get_s3_client():
    """Get or create the boto3 S3 client.

    Lazy-initialized so the module can be imported without
    requiring AWS credentials at import time (helps with testing).
    """
    global _s3_client  # noqa: PLW0603
    if _s3_client is None:
        settings = get_settings()
        _s3_client = boto3.client("s3", region_name=settings.aws_region)
    return _s3_client


async def upload_file(
    bucket: str,
    key: str,
    content: bytes,
    *,
    correlation_id: str | None = None,
) -> str:
    """Upload a file to S3.

    Args:
        bucket: Pre-provisioned S3 bucket name.
        key: S3 object key (path within the bucket).
        content: File content as bytes.
        correlation_id: Tracing ID for this request.

    Returns:
        S3 URI string (s3://bucket/key).

    Raises:
        ClientError: If S3 rejects the request (permissions, etc).
    """
    try:
        client = _get_s3_client()
        client.put_object(Bucket=bucket, Key=key, Body=content)
        s3_uri = f"s3://{bucket}/{key}"
        logger.info(
            "Uploaded to S3",
            extra={"s3_uri": s3_uri, "correlation_id": correlation_id},
        )
        return s3_uri
    except ClientError as err:
        error_code = err.response["Error"]["Code"]
        if error_code in ("AccessDenied", "AccessDeniedException"):
            logger.error(
                "S3 permission denied — check IAM policy for this bucket",
                extra={
                    "bucket": bucket,
                    "key": key,
                    "error_code": error_code,
                    "correlation_id": correlation_id,
                },
            )
        raise


async def download_file(
    bucket: str,
    key: str,
    *,
    correlation_id: str | None = None,
) -> bytes:
    """Download a file from S3.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        correlation_id: Tracing ID for this request.

    Returns:
        File content as bytes.

    Raises:
        FileNotFoundError: If the S3 object does not exist.
        ClientError: If access is denied or other S3 error.
    """
    try:
        client = _get_s3_client()
        response = client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()
        logger.info(
            "Downloaded from S3",
            extra={
                "bucket": bucket,
                "key": key,
                "size_bytes": len(content),
                "correlation_id": correlation_id,
            },
        )
        return content
    except ClientError as err:
        error_code = err.response["Error"]["Code"]
        if error_code == "NoSuchKey":
            raise FileNotFoundError(
                f"S3 object not found: s3://{bucket}/{key}"
            ) from err
        if error_code in ("AccessDenied", "AccessDeniedException"):
            logger.error(
                "S3 permission denied on download",
                extra={
                    "bucket": bucket,
                    "key": key,
                    "error_code": error_code,
                    "correlation_id": correlation_id,
                },
            )
        raise


def reset_client() -> None:
    """Reset the S3 client. Used in tests to inject moto mocks."""
    global _s3_client  # noqa: PLW0603
    _s3_client = None
