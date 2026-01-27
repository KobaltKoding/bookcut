"""Tests for database module."""

import tempfile
from pathlib import Path

import pytest

from bookcut.database import Database, LibraryBook


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_library.db"
        db = Database(db_path)
        yield db


@pytest.fixture
def sample_book():
    """Create a sample book for testing."""
    return LibraryBook(
        md5="abc123def456",
        title="Test Book Title",
        author="Test Author",
        format="epub",
        file_path="/tmp/test_book.epub",
        publisher="Test Publisher",
        info="EPUB",
        description="A test book description",
        thumbnail="http://example.com/cover.jpg",
        isbn="9781234567890",
    )


class TestDatabase:
    """Tests for Database class."""

    def test_init_creates_db(self, temp_db):
        """Test that database file is created on init."""
        assert temp_db.db_path.exists()

    def test_add_and_get_book(self, temp_db, sample_book):
        """Test adding and retrieving a book."""
        temp_db.add_book(sample_book)

        retrieved = temp_db.get_book(sample_book.md5)

        assert retrieved is not None
        assert retrieved.md5 == sample_book.md5
        assert retrieved.title == sample_book.title
        assert retrieved.author == sample_book.author
        assert retrieved.format == sample_book.format
        assert retrieved.isbn == sample_book.isbn

    def test_get_nonexistent_book(self, temp_db):
        """Test getting a book that doesn't exist."""
        result = temp_db.get_book("nonexistent_md5")
        assert result is None

    def test_book_exists(self, temp_db, sample_book):
        """Test book_exists method."""
        assert not temp_db.book_exists(sample_book.md5)

        temp_db.add_book(sample_book)

        assert temp_db.book_exists(sample_book.md5)

    def test_get_all_books(self, temp_db):
        """Test getting all books."""
        books = [
            LibraryBook(md5=f"md5_{i}", title=f"Book {i}", author=f"Author {i}",
                       format="epub", file_path=f"/tmp/book_{i}.epub")
            for i in range(3)
        ]

        for book in books:
            temp_db.add_book(book)

        all_books = temp_db.get_all_books()

        assert len(all_books) == 3
        titles = {b.title for b in all_books}
        assert titles == {"Book 0", "Book 1", "Book 2"}

    def test_remove_book(self, temp_db, sample_book):
        """Test removing a book."""
        temp_db.add_book(sample_book)
        assert temp_db.book_exists(sample_book.md5)

        result = temp_db.remove_book(sample_book.md5)

        assert result is True
        assert not temp_db.book_exists(sample_book.md5)

    def test_remove_nonexistent_book(self, temp_db):
        """Test removing a book that doesn't exist."""
        result = temp_db.remove_book("nonexistent_md5")
        assert result is False

    def test_search_books_by_title(self, temp_db):
        """Test searching books by title."""
        books = [
            LibraryBook(md5="1", title="Python Programming", author="John",
                       format="pdf", file_path="/tmp/1.pdf"),
            LibraryBook(md5="2", title="Java Basics", author="Jane",
                       format="epub", file_path="/tmp/2.epub"),
            LibraryBook(md5="3", title="Advanced Python", author="Bob",
                       format="mobi", file_path="/tmp/3.mobi"),
        ]
        for book in books:
            temp_db.add_book(book)

        results = temp_db.search_books("Python")

        assert len(results) == 2
        titles = {b.title for b in results}
        assert "Python Programming" in titles
        assert "Advanced Python" in titles

    def test_search_books_by_author(self, temp_db):
        """Test searching books by author."""
        books = [
            LibraryBook(md5="1", title="Book One", author="Haruki Murakami",
                       format="epub", file_path="/tmp/1.epub"),
            LibraryBook(md5="2", title="Book Two", author="Stephen King",
                       format="epub", file_path="/tmp/2.epub"),
        ]
        for book in books:
            temp_db.add_book(book)

        results = temp_db.search_books("Murakami")

        assert len(results) == 1
        assert results[0].author == "Haruki Murakami"

    def test_search_books_no_results(self, temp_db, sample_book):
        """Test search with no matching results."""
        temp_db.add_book(sample_book)

        results = temp_db.search_books("Nonexistent Query")

        assert len(results) == 0

    def test_add_book_replaces_existing(self, temp_db, sample_book):
        """Test that adding a book with same MD5 replaces it."""
        temp_db.add_book(sample_book)

        updated_book = LibraryBook(
            md5=sample_book.md5,
            title="Updated Title",
            author="Updated Author",
            format="pdf",
            file_path="/tmp/updated.pdf",
        )
        temp_db.add_book(updated_book)

        retrieved = temp_db.get_book(sample_book.md5)
        assert retrieved.title == "Updated Title"
        assert retrieved.author == "Updated Author"

        # Should still be just one book
        all_books = temp_db.get_all_books()
        assert len(all_books) == 1
