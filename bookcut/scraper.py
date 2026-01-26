"""Anna's Archive and LibGen scraper service."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup


@dataclass
class Book:
    """Book search result."""

    title: str
    author: str | None
    publisher: str | None
    info: str | None
    md5: str
    link: str
    thumbnail: str | None = None


@dataclass
class BookInfo(Book):
    """Detailed book information with download URL."""

    description: str | None = None
    format: str = "epub"
    download_url: str | None = None


class LibGenScraper:
    """Direct LibGen scraper (bypasses Anna's Archive)."""

    LIBGEN_MIRRORS = [
        "https://libgen.li",
        "https://libgen.is",
        "https://libgen.rs",
    ]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self) -> None:
        self.client = httpx.Client(headers=self.HEADERS, timeout=30.0, follow_redirects=True)
        self._working_mirror = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _find_working_mirror(self) -> str | None:
        """Find a working LibGen mirror."""
        if self._working_mirror:
            return self._working_mirror

        for mirror in self.LIBGEN_MIRRORS:
            try:
                response = self.client.get(mirror, timeout=10.0)
                if response.status_code == 200:
                    self._working_mirror = mirror
                    return mirror
            except Exception:
                continue
        return None

    def _get_format(self, ext: str) -> str:
        """Normalize format extension."""
        ext_lower = ext.lower().strip()
        if ext_lower in ("pdf", "epub", "mobi", "azw3", "cbr", "cbz", "djvu"):
            return ext_lower
        return "epub"

    def search(self, query: str, search_type: str = "def") -> list[Book]:
        """Search for books on LibGen directly.

        search_type can be: 'def' (default), 'title', 'author', 'isbn'
        """
        mirror = self._find_working_mirror()
        if not mirror:
            raise ConnectionError("No working LibGen mirror found")

        encoded_query = quote_plus(query)

        # LibGen search URL (libgen.li uses index.php)
        url = f"{mirror}/index.php?req={encoded_query}&columns%5B%5D={search_type}&objects%5B%5D=f&objects%5B%5D=e&objects%5B%5D=s&objects%5B%5D=a&objects%5B%5D=p&objects%5B%5D=w&topics%5B%5D=l&topics%5B%5D=c&topics%5B%5D=f&topics%5B%5D=a&topics%5B%5D=m&topics%5B%5D=r&topics%5B%5D=s&res=50"

        response = self.client.get(url)
        response.raise_for_status()

        return self._parse_search_results(response.text, mirror)

    def _parse_search_results(self, html: str, mirror: str) -> list[Book]:
        """Parse LibGen search results."""
        soup = BeautifulSoup(html, "lxml")

        # Find the results table (table with Author, Publisher columns in header)
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
        rows = results_table.find_all("tr")[1:]  # Skip header row

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            try:
                # libgen.li table structure:
                # Cell 0: Title + links (including MD5 link)
                # Cell 1: Author(s)
                # Cell 2: Publisher
                # Cell 3: Year
                # Cell 4: Language (etc.)

                title_cell = cells[0]
                title_link = title_cell.find("a")
                if not title_link:
                    continue

                title = title_link.get_text(strip=True)
                author = cells[1].get_text(strip=True) or "Unknown"
                publisher = cells[2].get_text(strip=True) if len(cells) > 2 else "Unknown"
                year = cells[3].get_text(strip=True) if len(cells) > 3 else ""

                # Find MD5 from ads.php link in the row
                md5 = ""
                for link in row.find_all("a"):
                    href = link.get("href", "")
                    if "/ads.php?md5=" in href:
                        md5 = href.split("md5=")[-1].split("&")[0]
                        break
                    elif "md5=" in href.lower():
                        md5 = href.lower().split("md5=")[-1].split("&")[0].split("?")[0]
                        break

                if not md5 or len(md5) != 32:
                    continue

                # Try to determine format from page text
                row_text = row.get_text(strip=True).lower()
                extension = "epub"
                for fmt in ("pdf", "epub", "mobi", "azw3", "cbr", "cbz", "djvu"):
                    if fmt in row_text:
                        extension = fmt
                        break

                info = f"{extension.upper()}" + (f", {year}" if year else "")

                books.append(
                    Book(
                        title=title,
                        author=author,
                        publisher=publisher or "Unknown",
                        info=info,
                        md5=md5.lower(),
                        link=f"{mirror}/ads.php?md5={md5}",
                        thumbnail=None,
                    )
                )
            except Exception:
                continue

        return books

    def get_book_info(self, md5: str) -> BookInfo | None:
        """Get book info from LibGen."""
        mirror = self._find_working_mirror()
        if not mirror:
            return None

        url = f"{mirror}/book/index.php?md5={md5}"
        try:
            response = self.client.get(url)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "lxml")

            # Parse book details from the page
            title = "Unknown"
            author = "Unknown"
            publisher = "Unknown"
            extension = "epub"

            # Try to find title in heading or table
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

            # Look for details table
            for row in soup.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)
                    if "title" in label and value:
                        title = value
                    elif "author" in label and value:
                        author = value
                    elif "publisher" in label and value:
                        publisher = value
                    elif "extension" in label and value:
                        extension = value.lower()

            return BookInfo(
                title=title,
                author=author,
                publisher=publisher,
                info=extension.upper(),
                md5=md5,
                link=url,
                thumbnail=None,
                description=None,
                format=self._get_format(extension),
                download_url=None,
            )
        except Exception:
            return None

    def get_download_url(self, md5: str) -> str | None:
        """Get direct download URL from LibGen."""
        for mirror in self.LIBGEN_MIRRORS:
            try:
                ads_url = f"{mirror}/ads.php?md5={md5}"
                response = self.client.get(ads_url)

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "lxml")

                # Find download link
                link = soup.select_one("#main > tr:first-child > td:nth-child(2) > a")
                if link and link.get("href"):
                    href = link["href"]
                    if href.startswith("http"):
                        return href
                    return f"{mirror}/{href}"

            except Exception:
                continue

        return None


class AnnasArchiveScraper:
    """Scraper for Anna's Archive (search) and LibGen (download)."""

    BASE_URL = "https://annas-archive.li"
    LIBGEN_MIRRORS = ["https://libgen.li", "https://libgen.vg", "https://libgen.gl"]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self) -> None:
        self.client = httpx.Client(headers=self.HEADERS, timeout=30.0, follow_redirects=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _get_md5(self, url: str) -> str:
        """Extract MD5 hash from URL path."""
        return url.rstrip("/").split("/")[-1]

    def _get_format(self, info: str) -> str:
        """Determine book format from info string."""
        info_lower = info.lower()
        for fmt in ("pdf", "cbr", "cbz", "mobi", "azw3"):
            if fmt in info_lower:
                return fmt
        return "epub"

    def _is_isbn(self, query: str) -> bool:
        """Check if query looks like an ISBN (10 or 13 digits, optional hyphens)."""
        digits = query.replace("-", "").replace(" ", "")
        return digits.isdigit() and len(digits) in (10, 13)

    def search(
        self,
        query: str,
        file_type: str = "",
        content: str = "",
        sort: str = "",
    ) -> list[Book]:
        """Search for books on Anna's Archive."""
        # If query looks like ISBN, format it for ISBN search
        if self._is_isbn(query):
            clean_isbn = query.replace("-", "").replace(" ", "")
            query = f"isbn:{clean_isbn}"

        encoded_query = quote_plus(query)

        if file_type or content or sort:
            url = (
                f"{self.BASE_URL}/search?index=&q={encoded_query}"
                f"&content={content}&ext={file_type}&sort={sort}"
            )
        else:
            url = f"{self.BASE_URL}/search?q={encoded_query}"

        response = self.client.get(url)
        response.raise_for_status()

        return self._parse_search_results(response.text, file_type)

    def _parse_search_results(self, html: str, file_type: str) -> list[Book]:
        """Parse search results HTML."""
        soup = BeautifulSoup(html, "lxml")
        containers = soup.select("div.flex.pt-3.pb-3.border-b")

        books = []
        for container in containers:
            main_link = container.select_one("a.js-vim-focus")
            if not main_link or not main_link.get("href"):
                continue

            title = main_link.get_text(strip=True)
            href = main_link["href"]
            link = f"{self.BASE_URL}{href}"
            md5 = self._get_md5(href)

            thumbnail_img = container.select_one('a[href^="/md5/"] img')
            thumbnail = thumbnail_img["src"] if thumbnail_img and thumbnail_img.get("src") else None

            author = None
            publisher = None
            sibling = main_link.find_next_sibling("a")
            if sibling and sibling.get("href", "").startswith("/search?q="):
                author = sibling.get_text(strip=True)
                next_sibling = sibling.find_next_sibling("a")
                if next_sibling and next_sibling.get("href", "").startswith("/search?q="):
                    publisher = next_sibling.get_text(strip=True)

            info_el = container.select_one("div.text-gray-800")
            info = info_el.get_text(strip=True) if info_el else None

            if file_type:
                if not info or file_type.lower() not in info.lower():
                    continue
            else:
                if not info or not any(
                    fmt in info.lower() for fmt in ("pdf", "epub", "cbr", "cbz")
                ):
                    continue

            books.append(
                Book(
                    title=title,
                    author=author or "Unknown",
                    publisher=publisher or "Unknown",
                    info=info,
                    md5=md5,
                    link=link,
                    thumbnail=thumbnail,
                )
            )

        return books

    def get_book_info(self, md5: str) -> BookInfo | None:
        """Get detailed book information from Anna's Archive."""
        url = f"{self.BASE_URL}/md5/{md5}"

        response = self.client.get(url)
        response.raise_for_status()

        return self._parse_book_info(response.text, url, md5)

    def _parse_book_info(self, html: str, url: str, md5: str) -> BookInfo | None:
        """Parse book detail page HTML."""
        soup = BeautifulSoup(html, "lxml")
        main = soup.select_one("div.main-inner")
        if not main:
            return None

        title_el = main.select_one("div.font-semibold.text-2xl")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        author_el = main.select_one("a[href^='/search?q='].text-base")
        author = author_el.get_text(strip=True) if author_el else "Unknown"

        publisher = "Unknown"
        if author_el:
            pub_el = author_el.find_next_sibling("a")
            if pub_el and pub_el.get("href", "").startswith("/search?q="):
                publisher = pub_el.get_text(strip=True)

        thumb_el = main.select_one('div[id^="list_cover_"] img')
        thumbnail = thumb_el["src"] if thumb_el and thumb_el.get("src") else None

        info_el = main.select_one("div.text-gray-800")
        info = info_el.get_text(strip=True) if info_el else ""

        description = None
        desc_label = main.select_one(
            "div.js-md5-top-box-description div.text-xs.text-gray-500.uppercase"
        )
        if desc_label and "description" in desc_label.get_text(strip=True).lower():
            desc_el = desc_label.find_next_sibling()
            if desc_el:
                description = desc_el.get_text(strip=True)

        return BookInfo(
            title=title,
            author=author,
            publisher=publisher,
            info=info,
            md5=md5,
            link=url,
            thumbnail=thumbnail,
            description=description,
            format=self._get_format(info),
            download_url=None,  # Will be fetched from LibGen
        )

    def get_download_url(self, md5: str) -> str | None:
        """Get direct download URL from LibGen mirrors."""
        for mirror in self.LIBGEN_MIRRORS:
            try:
                # Get the ads page which contains the download link
                ads_url = f"{mirror}/ads.php?md5={md5}"
                response = self.client.get(ads_url)

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "lxml")

                # Find download link (libgen-downloader approach)
                link = soup.select_one("#main > tr:first-child > td:nth-child(2) > a")
                if link and link.get("href"):
                    href = link["href"]
                    if href.startswith("http"):
                        return href
                    return f"{mirror}/{href}"

            except Exception:
                continue

        return None
