"""MinIO client singleton."""

from __future__ import annotations

from minio import Minio

from emerald.config import get_settings


class MinioClient:
    """MinIO client wrapper."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self._client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self.bucket = bucket

    @property
    def client(self) -> Minio:
        return self._client

    def ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self.bucket):
            self._client.make_bucket(self.bucket)

    def presigned_get_url(self, object_name: str, expires: int = 3600) -> str:
        return self._client.presigned_get_object(
            self.bucket, object_name, expires=expires
        )

    def presigned_put_url(self, object_name: str, expires: int = 3600) -> str:
        return self._client.presigned_put_object(
            self.bucket, object_name, expires=expires
        )


settings = get_settings()
minio_client = MinioClient(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    bucket=settings.minio_bucket,
    secure=settings.minio_secure,
)


def get_minio() -> MinioClient:
    """FastAPI dependency for MinIO client."""
    return minio_client
