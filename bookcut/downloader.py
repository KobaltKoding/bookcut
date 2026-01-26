"""Download service with multi-mirror support."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)


class DownloadError(Exception):
    """Download failed."""


class Downloader:
    """Handles book downloads with multi-mirror fallback."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Connection": "Keep-Alive",
    }

    def __init__(self, download_dir: Path | None = None) -> None:
        self.download_dir = download_dir or Path.home() / "BookCut"
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _reorder_mirrors(self, mirrors: list[str]) -> list[str]:
        """Reorder mirrors to prioritize IPFS and reliable sources."""
        ipfs = []
        https = []

        for url in mirrors:
            if "ipfs" in url or "dweb.link" in url:
                ipfs.append(url)
            elif not any(
                blocked in url for blocked in ["annas-archive.se", "1lib.sk"]
            ):
                https.append(url)

        return ipfs + https

    def _find_working_mirror(self, mirrors: list[str], timeout: float = 15.0) -> str | None:
        """Test mirrors and return the first working one."""
        if len(mirrors) == 1:
            return mirrors[0]

        with httpx.Client(headers=self.HEADERS, timeout=timeout, follow_redirects=True) as client:
            for url in mirrors:
                try:
                    response = client.head(url)
                    if response.status_code == 200:
                        return url
                except (httpx.RequestError, httpx.HTTPStatusError):
                    continue

        return None

    def download(
        self,
        mirrors: list[str],
        md5: str,
        format: str,
        verify_checksum: bool = True,
    ) -> Path:
        """
        Download a book from available mirrors.

        Args:
            mirrors: List of download URLs
            md5: Expected MD5 hash
            format: File format (epub, pdf, etc.)
            verify_checksum: Whether to verify MD5 after download

        Returns:
            Path to downloaded file

        Raises:
            DownloadError: If download fails
        """
        if not mirrors:
            raise DownloadError("No download mirrors available")

        ordered = self._reorder_mirrors(mirrors)
        working_url = self._find_working_mirror(ordered)

        if not working_url:
            raise DownloadError("No working mirrors found")

        filename = f"{md5}.{format}"
        filepath = self.download_dir / filename

        with httpx.Client(
            headers=self.HEADERS, timeout=300.0, follow_redirects=True
        ) as client:
            with client.stream("GET", working_url) as response:
                response.raise_for_status()

                total = int(response.headers.get("content-length", 0))

                with Progress(
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    TimeRemainingColumn(),
                ) as progress:
                    task = progress.add_task("Downloading", total=total)

                    with open(filepath, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))

        if verify_checksum:
            if not self.verify_md5(filepath, md5):
                filepath.unlink()
                raise DownloadError("MD5 checksum verification failed")

        return filepath

    def verify_md5(self, filepath: Path, expected: str) -> bool:
        """Verify file MD5 checksum."""
        md5_hash = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest().lower() == expected.lower()

    def get_file_path(self, md5: str, format: str) -> Path | None:
        """Get path to existing downloaded file."""
        filepath = self.download_dir / f"{md5}.{format}"
        return filepath if filepath.exists() else None
