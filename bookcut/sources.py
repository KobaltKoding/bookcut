"""Book search and download sources with waterfall fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup


# === Download Helper ===


def download_file(
    url: str,
    filepath: Path,
    on_status=None,
    timeout: float = 120.0,
) -> bool:
    """
    Download file from URL. Returns True on success, False on failure.
    Handles network errors gracefully for waterfall retry.
    """
    client = httpx.Client(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
        timeout=timeout,
        follow_redirects=True,
    )

    try:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        return True
    except httpx.RemoteProtocolError as e:
        if on_status:
            on_status(f"  Download interrupted: {e}")
        # Clean up partial file
        if filepath.exists():
            filepath.unlink()
        return False
    except httpx.TimeoutException as e:
        if on_status:
            on_status(f"  Download timed out: {e}")
        if filepath.exists():
            filepath.unlink()
        return False
    except httpx.HTTPStatusError as e:
        if on_status:
            on_status(f"  HTTP error: {e.response.status_code}")
        if filepath.exists():
            filepath.unlink()
        return False
    except Exception as e:
        if on_status:
            on_status(f"  Download failed: {e}")
        if filepath.exists():
            filepath.unlink()
        return False
    finally:
        client.close()


@dataclass
class BookMetadata:
    """Book metadata from search."""

    title: str
    author: str | None = None
    publisher: str | None = None
    year: str | None = None
    isbn: str | None = None
    description: str | None = None
    cover_url: str | None = None
    source: str = ""


@dataclass
class DownloadableBook:
    """Book available for download."""

    title: str
    author: str | None
    format: str
    size: str | None
    download_url: str
    isbn: str | None = None
    source: str = ""


class SearchSource(Protocol):
    """Protocol for book search sources."""

    def search(self, query: str) -> list[BookMetadata]:
        ...

    def search_by_isbn(self, isbn: str) -> BookMetadata | None:
        ...


class DownloadSource(Protocol):
    """Protocol for book download sources."""

    def find_download(self, isbn: str) -> list[DownloadableBook]:
        ...

    def find_download_by_title(self, title: str, author: str | None = None) -> list[DownloadableBook]:
        ...


# === Search Sources ===


class OpenLibrarySearch:
    """OpenLibrary search source."""

    BASE_URL = "https://openlibrary.org"
    COVERS_URL = "https://covers.openlibrary.org"

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def close(self):
        self.client.close()

    def search(self, query: str, limit: int = 10) -> list[BookMetadata]:
        """Search OpenLibrary by title/author."""
        encoded = quote_plus(query)
        url = f"{self.BASE_URL}/search.json?q={encoded}&limit={limit}"

        try:
            response = self.client.get(url)
            response.raise_for_status()
            data = response.json()

            results = []
            for doc in data.get("docs", []):
                isbn = self._extract_isbn(doc)

                if not isbn:
                    key = doc.get("key", "")
                    if key:
                        isbn = self._get_isbn_from_editions(key)

                cover_id = doc.get("cover_i")
                cover_url = f"{self.COVERS_URL}/b/id/{cover_id}-M.jpg" if cover_id else None

                results.append(
                    BookMetadata(
                        title=doc.get("title", "Unknown"),
                        author=doc.get("author_name", [None])[0],
                        publisher=doc.get("publisher", [None])[0],
                        year=str(doc.get("first_publish_year", "")) or None,
                        isbn=isbn,
                        cover_url=cover_url,
                        source="openlibrary",
                    )
                )

            return results
        except Exception:
            return []

    def search_by_isbn(self, isbn: str) -> BookMetadata | None:
        clean = isbn.replace("-", "").replace(" ", "")
        url = f"{self.BASE_URL}/isbn/{clean}.json"

        try:
            response = self.client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()

            author = None
            author_keys = data.get("authors", [])
            if author_keys:
                author_key = author_keys[0].get("key", "")
                if author_key:
                    author_resp = self.client.get(f"{self.BASE_URL}{author_key}.json")
                    if author_resp.status_code == 200:
                        author = author_resp.json().get("name")

            covers = data.get("covers", [])
            cover_url = f"{self.COVERS_URL}/b/id/{covers[0]}-M.jpg" if covers else None

            return BookMetadata(
                title=data.get("title", "Unknown"),
                author=author,
                publisher=data.get("publishers", [None])[0],
                year=data.get("publish_date"),
                isbn=clean,
                cover_url=cover_url,
                source="openlibrary",
            )
        except Exception:
            return None

    def _extract_isbn(self, doc: dict) -> str | None:
        for isbn in doc.get("isbn", []):
            if len(isbn.replace("-", "")) == 13:
                return isbn
        if doc.get("isbn"):
            return doc["isbn"][0]
        return None

    def _get_isbn_from_editions(self, work_key: str) -> str | None:
        try:
            url = f"{self.BASE_URL}{work_key}/editions.json?limit=5"
            response = self.client.get(url)
            if response.status_code != 200:
                return None

            data = response.json()
            for entry in data.get("entries", []):
                if entry.get("isbn_13"):
                    return entry["isbn_13"][0]
                if entry.get("isbn_10"):
                    return entry["isbn_10"][0]
            return None
        except Exception:
            return None


class GoogleBooksSearch:
    """Google Books search source."""

    BASE_URL = "https://www.googleapis.com/books/v1/volumes"

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def close(self):
        self.client.close()

    def search(self, query: str, limit: int = 10) -> list[BookMetadata]:
        encoded = quote_plus(query)
        url = f"{self.BASE_URL}?q={encoded}&maxResults={limit}"

        try:
            response = self.client.get(url)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("items", []):
                vol = item.get("volumeInfo", {})

                isbn = None
                for ident in vol.get("industryIdentifiers", []):
                    if ident.get("type") == "ISBN_13":
                        isbn = ident.get("identifier")
                        break
                    elif ident.get("type") == "ISBN_10" and not isbn:
                        isbn = ident.get("identifier")

                images = vol.get("imageLinks", {})
                cover_url = images.get("thumbnail") or images.get("smallThumbnail")

                results.append(
                    BookMetadata(
                        title=vol.get("title", "Unknown"),
                        author=vol.get("authors", [None])[0],
                        publisher=vol.get("publisher"),
                        year=vol.get("publishedDate", "")[:4] or None,
                        isbn=isbn,
                        description=vol.get("description"),
                        cover_url=cover_url,
                        source="googlebooks",
                    )
                )

            return results
        except Exception:
            return []

    def search_by_isbn(self, isbn: str) -> BookMetadata | None:
        clean = isbn.replace("-", "").replace(" ", "")
        url = f"{self.BASE_URL}?q=isbn:{clean}"

        try:
            response = self.client.get(url)
            response.raise_for_status()
            data = response.json()

            items = data.get("items", [])
            if not items:
                return None

            vol = items[0].get("volumeInfo", {})
            images = vol.get("imageLinks", {})

            return BookMetadata(
                title=vol.get("title", "Unknown"),
                author=vol.get("authors", [None])[0],
                publisher=vol.get("publisher"),
                year=vol.get("publishedDate", "")[:4] or None,
                isbn=clean,
                description=vol.get("description"),
                cover_url=images.get("thumbnail"),
                source="googlebooks",
            )
        except Exception:
            return None


# === Format Preference ===

PREFERRED_FORMATS = ["epub", "mobi", "azw3", "pdf", "djvu", "cbr", "cbz"]


def sort_by_format(books: list[DownloadableBook]) -> list[DownloadableBook]:
    """Sort books by preferred format (epub first)."""
    def sort_key(book: DownloadableBook) -> int:
        fmt = book.format.lower()
        try:
            return PREFERRED_FORMATS.index(fmt)
        except ValueError:
            return len(PREFERRED_FORMATS)
    return sorted(books, key=sort_key)


# === Download Sources ===


class LibGenDownload:
    """LibGen download source."""

    MIRRORS = ["https://libgen.li"]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self) -> None:
        self.client = httpx.Client(headers=self.HEADERS, timeout=30.0, follow_redirects=True)

    def close(self):
        self.client.close()

    def find_download(self, isbn: str) -> list[DownloadableBook]:
        clean = isbn.replace("-", "").replace(" ", "")
        return self._search(clean, search_type="identifier")

    def find_download_by_title(self, title: str, author: str | None = None) -> list[DownloadableBook]:
        query = title
        if author:
            query = f"{title} {author}"
        return self._search(query, search_type="def")

    def _search(self, query: str, search_type: str = "def") -> list[DownloadableBook]:
        encoded = quote_plus(query)

        for mirror in self.MIRRORS:
            try:
                url = (
                    f"{mirror}/index.php?req={encoded}"
                    f"&columns%5B%5D={search_type}"
                    "&objects%5B%5D=f&objects%5B%5D=e&objects%5B%5D=s"
                    "&objects%5B%5D=a&objects%5B%5D=p&objects%5B%5D=w"
                    "&topics%5B%5D=l&topics%5B%5D=c&topics%5B%5D=f"
                    "&topics%5B%5D=a&topics%5B%5D=m&topics%5B%5D=r&topics%5B%5D=s"
                    "&res=25"
                )

                response = self.client.get(url)
                if response.status_code != 200:
                    continue

                return self._parse_results(response.text, mirror)
            except Exception:
                continue

        return []

    def _parse_results(self, html: str, mirror: str) -> list[DownloadableBook]:
        soup = BeautifulSoup(html, "lxml")

        tables = soup.find_all("table")
        results_table = None
        for table in tables:
            first_row = table.find("tr")
            if first_row:
                header_text = first_row.get_text(strip=True).lower()
                if "author" in header_text and "publisher" in header_text:
                    results_table = table
                    break

        if not results_table:
            return []

        books = []
        rows = results_table.find_all("tr")[1:]

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            try:
                title_link = cells[0].find("a")
                if not title_link:
                    continue

                title = title_link.get_text(strip=True)
                author = cells[1].get_text(strip=True) or None

                md5 = None
                for link in row.find_all("a"):
                    href = link.get("href", "")
                    if "/ads.php?md5=" in href:
                        md5 = href.split("md5=")[-1].split("&")[0]
                        break

                if not md5 or len(md5) != 32:
                    continue

                row_text = row.get_text(strip=True).lower()
                fmt = "epub"
                for f in ("pdf", "epub", "mobi", "azw3", "cbr", "cbz", "djvu"):
                    if f in row_text:
                        fmt = f
                        break

                download_url = self._get_download_url(mirror, md5)
                if not download_url:
                    continue

                books.append(
                    DownloadableBook(
                        title=title,
                        author=author,
                        format=fmt,
                        size=None,
                        download_url=download_url,
                        source="libgen",
                    )
                )
            except Exception:
                continue

        return books

    def _get_download_url(self, mirror: str, md5: str) -> str | None:
        try:
            ads_url = f"{mirror}/ads.php?md5={md5}"
            response = self.client.get(ads_url)

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "lxml")

            link = soup.select_one("#main > tr:first-child > td:nth-child(2) > a")
            if link and link.get("href"):
                href = link["href"]
                if href.startswith("http"):
                    return href
                return f"{mirror}/{href}"
        except Exception:
            pass

        return None


# === Waterfall Manager ===


class BookFinder:
    """Coordinates search and download across multiple sources."""

    def __init__(self) -> None:
        self.search_sources = [
            OpenLibrarySearch(),
            GoogleBooksSearch(),
        ]
        self.download_sources = [
            LibGenDownload(),
        ]

    def close(self):
        for source in self.search_sources:
            source.close()
        for source in self.download_sources:
            source.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _title_match_score(self, query: str, title: str) -> float:
        """Score how well a title matches the query (0-1)."""
        query_lower = query.lower()
        title_lower = title.lower()

        collection_terms = ["box set", "collection", "books set", "complete series", "omnibus"]
        is_collection = any(term in title_lower for term in collection_terms)

        stop_words = {"the", "a", "an", "of", "and", "to", "in", "for", "on", "with", "by"}

        def clean_words(text):
            return set(w for w in text.split() if w not in stop_words and len(w) > 2)

        if query_lower == title_lower:
            return 1.0

        if title_lower.startswith(query_lower):
            return 0.95 if not is_collection else 0.6

        if query_lower in title_lower:
            return 0.9 if not is_collection else 0.55

        query_words = clean_words(query_lower)
        title_words = clean_words(title_lower)

        if not query_words:
            return 0.0

        overlap = query_words & title_words
        overlap_ratio = len(overlap) / len(query_words)

        if overlap_ratio >= 0.5:
            base_score = 0.5 + (0.4 * overlap_ratio)

            if is_collection:
                base_score *= 0.6

            title_word_count = len(title_lower.split())
            if title_word_count > 15:
                base_score *= 0.8

            return base_score

        return 0.0

    def collect_isbns(self, query: str, on_status=None) -> tuple[BookMetadata | None, list[str]]:
        """Collect all ISBNs for a book from all search sources."""
        all_isbns = []
        seen_isbns = set()
        best_metadata = None
        best_score = 0.0

        for source in self.search_sources:
            source_name = source.__class__.__name__
            if on_status:
                on_status(f"Searching {source_name}...")

            try:
                results = source.search(query, limit=10)
                matching_count = 0

                for r in results:
                    score = self._title_match_score(query, r.title)

                    if score < 0.5:
                        continue

                    if "summary" in r.title.lower():
                        continue

                    if score > best_score and r.isbn:
                        best_metadata = r
                        best_score = score

                    if r.isbn:
                        clean = r.isbn.replace("-", "").replace(" ", "")
                        if clean not in seen_isbns:
                            seen_isbns.add(clean)
                            all_isbns.append(clean)
                            matching_count += 1

                if on_status:
                    on_status(f"  Found {matching_count} matching ISBNs from {source_name}")
            except Exception as e:
                if on_status:
                    on_status(f"  {source_name} failed: {e}")
                continue

        if not best_metadata:
            for source in self.search_sources:
                try:
                    results = source.search(query, limit=5)
                    for r in results:
                        if self._title_match_score(query, r.title) >= 0.5:
                            if "summary" not in r.title.lower():
                                best_metadata = r
                                break
                    if best_metadata:
                        break
                except Exception:
                    continue

        return best_metadata, all_isbns

    def find_download_by_isbn(self, isbn: str, expected_title: str | None = None, on_status=None) -> DownloadableBook | None:
        """Try to find a download for a specific ISBN. Prefers epub format."""
        all_downloads = []

        for source in self.download_sources:
            try:
                downloads = source.find_download(isbn)
                for download in downloads:
                    if expected_title:
                        score = self._title_match_score(expected_title, download.title)
                        if score < 0.5:
                            continue
                    all_downloads.append(download)
            except Exception:
                continue

        if not all_downloads:
            return None

        # Sort by format preference (epub first)
        sorted_downloads = sort_by_format(all_downloads)
        best = sorted_downloads[0]

        if on_status:
            on_status(f"  Found '{best.title}' ({best.format.upper()}) on {best.source}!")

        return best

    def find_download_by_title(self, title: str, author: str | None, on_status=None) -> DownloadableBook | None:
        """Try to find a download by title/author. Prefers epub format."""
        all_downloads = []

        for source in self.download_sources:
            source_name = source.__class__.__name__
            if on_status:
                on_status(f"Searching {source_name} by title...")
            try:
                downloads = source.find_download_by_title(title, author)
                all_downloads.extend(downloads)
            except Exception:
                continue

        if not all_downloads:
            return None

        # Sort by format preference (epub first)
        sorted_downloads = sort_by_format(all_downloads)
        best = sorted_downloads[0]

        if on_status:
            on_status(f"  Found '{best.title}' ({best.format.upper()}) on {best.source}!")

        return best

    def find_book_and_download(
        self,
        query: str,
        download_dir: Path | None = None,
        on_status=None,
    ) -> tuple[BookMetadata | None, DownloadableBook | None, Path | None]:
        """
        Search for a book and download it using waterfall approach.

        If download_dir is provided, actually downloads the file and retries
        on failure with the next ISBN. Returns (metadata, download_info, filepath).

        If download_dir is None, just finds download info without downloading.
        Returns (metadata, download_info, None).
        """
        if on_status:
            on_status("Phase 1: Collecting ISBNs from metadata sources...")

        metadata, isbns = self.collect_isbns(query, on_status)

        if not metadata:
            if on_status:
                on_status("No book metadata found.")
            return None, None, None

        if on_status:
            on_status(f"\nFound book: {metadata.title}")
            if metadata.author:
                on_status(f"Author: {metadata.author}")
            on_status(f"Collected {len(isbns)} unique ISBN(s): {', '.join(isbns[:5])}{'...' if len(isbns) > 5 else ''}")

        if isbns:
            if on_status:
                on_status("\nPhase 2: Trying ISBNs for download...")

            for i, isbn in enumerate(isbns):
                if on_status:
                    on_status(f"Trying ISBN {i+1}/{len(isbns)}: {isbn}")

                download = self.find_download_by_isbn(isbn, expected_title=metadata.title, on_status=on_status)
                if download:
                    download.isbn = isbn

                    # If no download_dir, just return the download info
                    if download_dir is None:
                        return metadata, download, None

                    # Attempt actual download
                    filepath = self._attempt_download(download, metadata, download_dir, on_status)
                    if filepath:
                        return metadata, download, filepath
                    else:
                        if on_status:
                            on_status(f"  Trying next ISBN...")
                        continue

        if on_status:
            on_status("\nPhase 3: Falling back to title search...")

        download = self.find_download_by_title(metadata.title, metadata.author, on_status)
        if download:
            if download_dir is None:
                return metadata, download, None

            filepath = self._attempt_download(download, metadata, download_dir, on_status)
            if filepath:
                return metadata, download, filepath

        if on_status:
            on_status("No download found.")
        return metadata, None, None

    def _attempt_download(
        self,
        download: DownloadableBook,
        metadata: BookMetadata,
        download_dir: Path,
        on_status=None,
    ) -> Path | None:
        """Attempt to download a file. Returns filepath on success, None on failure."""
        import re

        def sanitize(s: str) -> str:
            return re.sub(r'[/\\:*?"<>|]', "", s).strip()

        # Create filename
        title = sanitize(download.title)
        author = sanitize(download.author or metadata.author or "Unknown")

        if author and author.lower() != "unknown":
            name = f"{title} - {author}"
        else:
            name = title

        if len(name) > 200:
            name = name[:200].rsplit(" ", 1)[0]

        filename = f"{name}.{download.format}"
        filepath = download_dir / filename

        # Handle duplicates
        counter = 1
        base_filepath = filepath
        while filepath.exists():
            stem = base_filepath.stem
            filepath = download_dir / f"{stem} ({counter}).{download.format}"
            counter += 1

        if on_status:
            on_status(f"  Downloading to: {filename}")

        success = download_file(download.download_url, filepath, on_status)

        if success:
            return filepath
        return None
