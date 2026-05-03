"""
DigitalOcean Spaces object storage service.

All paths are automatically scoped to the current tenant:
  {TENANT_SLUG}/{ENVIRONMENT}/{path}

This ensures complete data isolation between tenant pods even when
they share a single DO Spaces bucket.

Usage:
    from app.services.storage import storage

    url = await storage.upload(b"...", "exports/orders-2026.csv", content_type="text/csv")
    data = await storage.download("exports/orders-2026.csv")
    await storage.delete("exports/orders-2026.csv")
    urls = await storage.list_files(prefix="exports/")
    signed = await storage.presigned_url("exports/orders-2026.csv", expires_in=3600)

Requirements:
    pip install boto3  (boto3 is S3-compatible; DO Spaces uses the same API)
"""
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(settings.SPACES_KEY and settings.SPACES_SECRET and settings.SPACES_ENDPOINT and settings.SPACES_BUCKET)


def _tenant_prefix() -> str:
    """Scoped path prefix: <tenant>/<environment>/"""
    return f"{settings.TENANT_SLUG}/{settings.ENVIRONMENT}"


def _full_key(path: str) -> str:
    """Build the full object key including tenant prefix."""
    # Strip leading slash so we don't get double slashes
    return f"{_tenant_prefix()}/{path.lstrip('/')}"


def _get_client():
    """Create a boto3 S3 client pointed at DO Spaces."""
    try:
        import boto3
    except ImportError:
        raise RuntimeError(
            "boto3 is required for storage operations. "
            "Add 'boto3' to requirements.txt and rebuild the container."
        )

    return boto3.client(
        "s3",
        region_name=settings.SPACES_REGION,
        endpoint_url=settings.SPACES_ENDPOINT,
        aws_access_key_id=settings.SPACES_KEY,
        aws_secret_access_key=settings.SPACES_SECRET,
    )


class StorageService:
    """
    Tenant-scoped wrapper around DigitalOcean Spaces (S3-compatible API).

    All methods are synchronous internally but wrapped in asyncio.to_thread
    so they can be awaited from async routes without blocking the event loop.
    """

    def _require_config(self) -> None:
        if not _is_configured():
            raise RuntimeError(
                "DO Spaces is not configured. Set SPACES_BUCKET, SPACES_REGION, "
                "SPACES_KEY, SPACES_SECRET, and SPACES_ENDPOINT environment variables."
            )

    async def upload(
        self,
        data: bytes,
        path: str,
        content_type: str = "application/octet-stream",
        public: bool = False,
    ) -> str:
        """
        Upload bytes to Spaces. Returns the public (or private) URL.

        Args:
            data: Raw bytes to upload.
            path: Path within tenant scope (e.g. "exports/orders.csv").
            content_type: MIME type of the object.
            public: If True, sets ACL to public-read.
        """
        import asyncio
        self._require_config()
        key = _full_key(path)

        def _upload():
            client = _get_client()
            extra = {"ContentType": content_type}
            if public:
                extra["ACL"] = "public-read"
            client.put_object(Bucket=settings.SPACES_BUCKET, Key=key, Body=data, **extra)
            return f"{settings.SPACES_ENDPOINT}/{settings.SPACES_BUCKET}/{key}"

        url = await asyncio.to_thread(_upload)
        logger.info("Uploaded %s (%d bytes) → %s", path, len(data), key)
        return url

    async def download(self, path: str) -> bytes:
        """Download an object and return its raw bytes."""
        import asyncio
        self._require_config()
        key = _full_key(path)

        def _download():
            client = _get_client()
            response = client.get_object(Bucket=settings.SPACES_BUCKET, Key=key)
            return response["Body"].read()

        return await asyncio.to_thread(_download)

    async def delete(self, path: str) -> None:
        """Delete an object."""
        import asyncio
        self._require_config()
        key = _full_key(path)

        def _delete():
            client = _get_client()
            client.delete_object(Bucket=settings.SPACES_BUCKET, Key=key)

        await asyncio.to_thread(_delete)
        logger.info("Deleted storage object: %s", key)

    async def list_files(self, prefix: str = "") -> list[dict]:
        """
        List objects under a path prefix (scoped to this tenant).

        Returns a list of dicts: {key, size, last_modified}
        """
        import asyncio
        self._require_config()
        full_prefix = _full_key(prefix) if prefix else f"{_tenant_prefix()}/"

        def _list():
            client = _get_client()
            paginator = client.get_paginator("list_objects_v2")
            results = []
            for page in paginator.paginate(Bucket=settings.SPACES_BUCKET, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    # Strip tenant prefix from returned key so callers see relative paths
                    relative_key = obj["Key"].removeprefix(f"{_tenant_prefix()}/")
                    results.append({
                        "key": relative_key,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    })
            return results

        return await asyncio.to_thread(_list)

    async def presigned_url(self, path: str, expires_in: int = 3600) -> str:
        """
        Generate a pre-signed GET URL valid for `expires_in` seconds.
        Use this to give users temporary download access to private objects.
        """
        import asyncio
        self._require_config()
        key = _full_key(path)

        def _presign():
            client = _get_client()
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.SPACES_BUCKET, "Key": key},
                ExpiresIn=expires_in,
            )

        return await asyncio.to_thread(_presign)


# Module-level singleton
storage = StorageService()
