"""Files of a service in S3-compatible storage: one bucket per service.

  TWIN_S3_ENDPOINT    e.g. http://s3:9000 (default: the dev stack's, http://127.0.0.1:9002)
  TWIN_S3_ACCESS_KEY / TWIN_S3_SECRET_KEY
  TWIN_S3_BUCKET      default: twin-<service>

The database keeps only keys. Calls block: use asyncio.to_thread from handlers.
Needs the extra: twin-chassis[files].
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path


class Bucket:
    def __init__(self, service: str, *, endpoint: str | None = None, bucket: str | None = None):
        import boto3
        from botocore.config import Config

        env = os.environ
        self.name = bucket or env.get("TWIN_S3_BUCKET") or f"twin-{service}"
        self._s3 = boto3.client(
            "s3", endpoint_url=endpoint or env.get("TWIN_S3_ENDPOINT", "http://127.0.0.1:9002"),
            aws_access_key_id=env.get("TWIN_S3_ACCESS_KEY", "twin"),
            aws_secret_access_key=env.get("TWIN_S3_SECRET_KEY", "twin-secret"), region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          retries={"max_attempts": 3}, connect_timeout=5, read_timeout=60))
        self._ready = False

    def _ensure(self) -> None:
        if self._ready:
            return
        from botocore.exceptions import ClientError
        try:
            self._s3.head_bucket(Bucket=self.name)
        except ClientError:
            try:
                self._s3.create_bucket(Bucket=self.name)
            except ClientError as ex:
                if ex.response.get("Error", {}).get("Code") not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise
        self._ready = True

    @staticmethod
    def _missing(ex) -> bool:
        return ex.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound")

    def put_file(self, key: str, src: Path, content_type: str | None = None) -> None:
        self._ensure()
        extra = {"ContentType": content_type} if content_type else None
        self._s3.upload_file(str(src), self.name, key, ExtraArgs=extra)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self._ensure()
        extra = {"ContentType": content_type} if content_type else {}
        self._s3.put_object(Bucket=self.name, Key=key, Body=data, **extra)

    def get_bytes(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError
        self._ensure()
        try:
            return self._s3.get_object(Bucket=self.name, Key=key)["Body"].read()
        except ClientError as ex:
            if self._missing(ex):
                return None
            raise

    def download(self, key: str, dst: Path) -> bool:
        from botocore.exceptions import ClientError
        self._ensure()
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._s3.download_file(self.name, key, str(dst))
            return True
        except ClientError as ex:
            if self._missing(ex):
                return False
            raise

    def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError
        self._ensure()
        try:
            return self._s3.head_object(Bucket=self.name, Key=key)["ContentLength"]
        except ClientError as ex:
            if self._missing(ex):
                return None
            raise

    def stream(self, key: str, chunk: int = 1 << 16) -> Iterator[bytes]:
        self._ensure()
        yield from self._s3.get_object(Bucket=self.name, Key=key)["Body"].iter_chunks(chunk)

    def list(self, prefix: str) -> dict[str, int]:
        self._ensure()
        out: dict[str, int] = {}
        for page in self._s3.get_paginator("list_objects_v2").paginate(Bucket=self.name, Prefix=prefix):
            out.update({o["Key"]: o["Size"] for o in page.get("Contents", [])})
        return out

    def delete_prefix(self, prefix: str) -> None:
        keys = list(self.list(prefix))
        for i in range(0, len(keys), 1000):
            self._s3.delete_objects(Bucket=self.name, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})

    def ok(self) -> bool:
        try:
            self._ensure()
            return True
        except Exception:
            return False
