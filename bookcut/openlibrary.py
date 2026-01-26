"""OpenLibrary search service."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx


@dataclass
class OpenLibraryBook:
    """Book search result from OpenLibrary."""

    title: str
    author: str | None
    publisher: str | None
    year: str | None
    isbn: str | None
    cover_url: str | None
    key: str  # OpenLibrary work key


class OpenLibraryScraper:
    """Search for books using OpenLibrary API."""

    BASE_URL = "https://openlibrary.org"
    COVERS_URL = "https://covers.openlibrary.org"

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def search(self, query: str, limit: int = 20) -> list[OpenLibraryBook]:
        """Search for books on OpenLibrary."""
        encoded_query = quote_plus(query)
        url = f"{self.BASE_URL}/search.json?q={encoded_query}&limit={limit}"

        response = self.client.get(url)
        response.raise_for_status()

        data = response.json()
        books = []

        for doc in data.get("docs", []):
            title = doc.get("title", "Unknown Title")

            authors = doc.get("author_name", [])
            author = authors[0] if authors else None

            publishers = doc.get("publisher", [])
            publisher = publishers[0] if publishers else None

            year = doc.get("first_publish_year")

            # Get ISBN (prefer ISBN-13)
            isbn = None
            isbn_13 = doc.get("isbn", [])
            for i in isbn_13:
                if len(i.replace("-", "")) == 13:
                    isbn = i
                    break
            if not isbn and isbn_13:
                isbn = isbn_13[0]

            # If no ISBN in search results, try to get from editions
            key = doc.get("key", "")
            if not isbn and key:
                isbn = self._get_isbn_from_editions(key)

            # Cover URL
            cover_id = doc.get("cover_i")
            cover_url = f"{self.COVERS_URL}/b/id/{cover_id}-M.jpg" if cover_id else None

            books.append(
                OpenLibraryBook(
                    title=title,
                    author=author,
                    publisher=publisher,
                    year=str(year) if year else None,
                    isbn=isbn,
                    cover_url=cover_url,
                    key=key,
                )
            )

        return books

    def _get_isbn_from_editions(self, work_key: str) -> str | None:
        """Get ISBN from work editions."""
        try:
            url = f"{self.BASE_URL}{work_key}/editions.json?limit=5"
            response = self.client.get(url)
            if response.status_code != 200:
                return None

            data = response.json()
            for entry in data.get("entries", []):
                isbn_13 = entry.get("isbn_13", [])
                if isbn_13:
                    return isbn_13[0]
                isbn_10 = entry.get("isbn_10", [])
                if isbn_10:
                    return isbn_10[0]
            return None
        except Exception:
            return None

    def get_book_by_isbn(self, isbn: str) -> OpenLibraryBook | None:
        """Get book info by ISBN."""
        clean_isbn = isbn.replace("-", "").replace(" ", "")
        url = f"{self.BASE_URL}/isbn/{clean_isbn}.json"

        try:
            response = self.client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()

            data = response.json()
            title = data.get("title", "Unknown Title")

            # Get author info (requires additional request)
            author = None
            author_keys = data.get("authors", [])
            if author_keys:
                author_key = author_keys[0].get("key", "")
                if author_key:
                    author_resp = self.client.get(f"{self.BASE_URL}{author_key}.json")
                    if author_resp.status_code == 200:
                        author_data = author_resp.json()
                        author = author_data.get("name")

            publishers = data.get("publishers", [])
            publisher = publishers[0] if publishers else None

            year = data.get("publish_date")

            covers = data.get("covers", [])
            cover_url = f"{self.COVERS_URL}/b/id/{covers[0]}-M.jpg" if covers else None

            return OpenLibraryBook(
                title=title,
                author=author,
                publisher=publisher,
                year=year,
                isbn=clean_isbn,
                cover_url=cover_url,
                key=data.get("key", ""),
            )
        except Exception:
            return None
