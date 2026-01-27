"""Tests for sources module."""

import pytest

from bookcut.sources import (
    BookMetadata,
    DownloadableBook,
    OpenLibrarySearch,
    GoogleBooksSearch,
    LibGenDownload,
    BookFinder,
    sort_by_format,
    PREFERRED_FORMATS,
)


class TestBookMetadata:
    """Tests for BookMetadata dataclass."""

    def test_create_minimal(self):
        """Test creating BookMetadata with minimal fields."""
        meta = BookMetadata(title="Test Book")
        assert meta.title == "Test Book"
        assert meta.author is None
        assert meta.isbn is None

    def test_create_full(self):
        """Test creating BookMetadata with all fields."""
        meta = BookMetadata(
            title="Test Book",
            author="Test Author",
            publisher="Test Publisher",
            year="2024",
            isbn="9781234567890",
            description="A description",
            cover_url="http://example.com/cover.jpg",
            source="openlibrary",
        )
        assert meta.title == "Test Book"
        assert meta.author == "Test Author"
        assert meta.isbn == "9781234567890"
        assert meta.source == "openlibrary"


class TestDownloadableBook:
    """Tests for DownloadableBook dataclass."""

    def test_create(self):
        """Test creating DownloadableBook."""
        book = DownloadableBook(
            title="Test Book",
            author="Test Author",
            format="epub",
            size="1.5 MB",
            download_url="http://example.com/download",
            isbn="9781234567890",
            source="libgen",
        )
        assert book.title == "Test Book"
        assert book.format == "epub"
        assert book.download_url == "http://example.com/download"


class TestSortByFormat:
    """Tests for sort_by_format function."""

    def test_sort_prefers_epub(self):
        """Test that EPUB is preferred over other formats."""
        books = [
            DownloadableBook(title="Book", author=None, format="pdf",
                           size=None, download_url="http://a"),
            DownloadableBook(title="Book", author=None, format="epub",
                           size=None, download_url="http://b"),
            DownloadableBook(title="Book", author=None, format="mobi",
                           size=None, download_url="http://c"),
        ]

        sorted_books = sort_by_format(books)

        assert sorted_books[0].format == "epub"
        assert sorted_books[1].format == "mobi"
        assert sorted_books[2].format == "pdf"

    def test_sort_with_unknown_format(self):
        """Test sorting with unknown format."""
        books = [
            DownloadableBook(title="Book", author=None, format="xyz",
                           size=None, download_url="http://a"),
            DownloadableBook(title="Book", author=None, format="epub",
                           size=None, download_url="http://b"),
        ]

        sorted_books = sort_by_format(books)

        assert sorted_books[0].format == "epub"
        assert sorted_books[1].format == "xyz"

    def test_sort_empty_list(self):
        """Test sorting empty list."""
        result = sort_by_format([])
        assert result == []

    def test_preferred_formats_order(self):
        """Test that PREFERRED_FORMATS has correct order."""
        assert PREFERRED_FORMATS[0] == "epub"
        assert "mobi" in PREFERRED_FORMATS
        assert "pdf" in PREFERRED_FORMATS
        assert PREFERRED_FORMATS.index("epub") < PREFERRED_FORMATS.index("pdf")


class TestTitleMatchScore:
    """Tests for BookFinder._title_match_score method."""

    @pytest.fixture
    def finder(self):
        """Create a BookFinder instance."""
        finder = BookFinder()
        yield finder
        finder.close()

    def test_exact_match(self, finder):
        """Test exact title match."""
        score = finder._title_match_score("Norwegian Wood", "Norwegian Wood")
        assert score == 1.0

    def test_case_insensitive_match(self, finder):
        """Test case insensitive matching."""
        score = finder._title_match_score("norwegian wood", "Norwegian Wood")
        assert score == 1.0

    def test_title_starts_with_query(self, finder):
        """Test when title starts with query."""
        score = finder._title_match_score(
            "Norwegian Wood",
            "Norwegian Wood: A Novel"
        )
        assert score >= 0.9

    def test_query_contained_in_title(self, finder):
        """Test when query is contained in title."""
        score = finder._title_match_score(
            "Cold Start",
            "The Cold Start Problem"
        )
        assert score >= 0.8

    def test_partial_word_match(self, finder):
        """Test partial word matching."""
        score = finder._title_match_score(
            "man died twice",
            "The Man Who Died Twice"
        )
        assert score >= 0.5

    def test_no_match(self, finder):
        """Test completely different titles."""
        score = finder._title_match_score(
            "Norwegian Wood",
            "Harry Potter"
        )
        assert score < 0.5

    def test_collection_penalty(self, finder):
        """Test that collections get penalized."""
        standalone_score = finder._title_match_score(
            "The Man Who Died Twice",
            "The Man Who Died Twice"
        )
        collection_score = finder._title_match_score(
            "The Man Who Died Twice",
            "The Man Who Died Twice Box Set Collection"
        )
        assert standalone_score > collection_score

    def test_long_title_penalty(self, finder):
        """Test that very long titles get penalized in word overlap scoring."""
        # Use titles that trigger word overlap scoring (not exact/starts-with match)
        short_score = finder._title_match_score(
            "programming python basics",
            "Python Programming Guide"
        )
        long_score = finder._title_match_score(
            "programming python basics",
            "Python Programming Guide With Extra Words That Make This Title Very Long And Extended Beyond Normal Length"
        )
        assert short_score > long_score


class TestOpenLibrarySearch:
    """Tests for OpenLibrarySearch class."""

    @pytest.fixture
    def search(self):
        """Create an OpenLibrarySearch instance."""
        s = OpenLibrarySearch()
        yield s
        s.close()

    def test_init(self, search):
        """Test initialization."""
        assert search.client is not None
        assert search.BASE_URL == "https://openlibrary.org"

    @pytest.mark.integration
    def test_search_real_api(self, search):
        """Integration test: search for a real book."""
        results = search.search("Norwegian Wood Murakami", limit=3)

        assert len(results) > 0
        # At least one result should have the right title
        titles = [r.title.lower() for r in results]
        assert any("norwegian" in t for t in titles)

    @pytest.mark.integration
    def test_search_by_isbn_real_api(self, search):
        """Integration test: search by ISBN."""
        # ISBN for Norwegian Wood
        result = search.search_by_isbn("9780375704024")

        if result:  # May fail due to network
            assert "norwegian" in result.title.lower() or result.isbn


class TestGoogleBooksSearch:
    """Tests for GoogleBooksSearch class."""

    @pytest.fixture
    def search(self):
        """Create a GoogleBooksSearch instance."""
        s = GoogleBooksSearch()
        yield s
        s.close()

    def test_init(self, search):
        """Test initialization."""
        assert search.client is not None
        assert "googleapis.com" in search.BASE_URL

    @pytest.mark.integration
    def test_search_real_api(self, search):
        """Integration test: search for a real book."""
        results = search.search("The Cold Start Problem", limit=3)

        assert len(results) > 0


class TestLibGenDownload:
    """Tests for LibGenDownload class."""

    @pytest.fixture
    def downloader(self):
        """Create a LibGenDownload instance."""
        d = LibGenDownload()
        yield d
        d.close()

    def test_init(self, downloader):
        """Test initialization."""
        assert downloader.client is not None
        assert len(downloader.MIRRORS) > 0

    def test_headers_set(self, downloader):
        """Test that User-Agent header is set."""
        assert "User-Agent" in downloader.HEADERS


class TestBookFinder:
    """Tests for BookFinder class."""

    @pytest.fixture
    def finder(self):
        """Create a BookFinder instance."""
        f = BookFinder()
        yield f
        f.close()

    def test_init(self, finder):
        """Test initialization."""
        assert len(finder.search_sources) == 2
        assert len(finder.download_sources) == 1

    def test_context_manager(self):
        """Test using BookFinder as context manager."""
        with BookFinder() as finder:
            assert finder is not None

    @pytest.mark.integration
    def test_collect_isbns_real_api(self, finder):
        """Integration test: collect ISBNs for a book."""
        statuses = []
        def on_status(msg):
            statuses.append(msg)

        metadata, isbns = finder.collect_isbns(
            "Norwegian Wood Murakami",
            on_status=on_status
        )

        assert metadata is not None
        assert len(isbns) > 0
        assert len(statuses) > 0  # Status callbacks were called

    @pytest.mark.integration
    def test_find_book_and_download_real_api(self, finder):
        """Integration test: full waterfall search (without actual download)."""
        statuses = []
        def on_status(msg):
            statuses.append(msg)

        # Don't pass download_dir to skip actual download
        metadata, download, filepath = finder.find_book_and_download(
            "Norwegian Wood",
            download_dir=None,
            on_status=on_status
        )

        # Should at least find metadata
        assert metadata is not None
        assert "norwegian" in metadata.title.lower()
        assert filepath is None  # No download attempted
        # Download may or may not be found depending on LibGen availability
