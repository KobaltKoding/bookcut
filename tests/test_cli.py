"""Tests for CLI module."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from bookcut.cli import app, _truncate, _make_filename, _is_isbn


runner = CliRunner()


class TestHelperFunctions:
    """Tests for CLI helper functions."""

    def test_truncate_short_string(self):
        """Test truncate with string shorter than limit."""
        result = _truncate("Hello", 10)
        assert result == "Hello"

    def test_truncate_long_string(self):
        """Test truncate with string longer than limit."""
        result = _truncate("Hello World", 5)
        assert result == "Hello..."

    def test_truncate_none(self):
        """Test truncate with None."""
        result = _truncate(None)
        assert result == ""

    def test_truncate_empty(self):
        """Test truncate with empty string."""
        result = _truncate("")
        assert result == ""

    def test_make_filename_with_author(self):
        """Test filename generation with author."""
        result = _make_filename("Test Book", "John Doe", "epub")
        assert result == "Test Book - John Doe.epub"

    def test_make_filename_without_author(self):
        """Test filename generation without author."""
        result = _make_filename("Test Book", "Unknown", "pdf")
        assert result == "Test Book.pdf"

    def test_make_filename_sanitizes_chars(self):
        """Test that problematic characters are removed."""
        result = _make_filename("Test: Book?", "Author/Name", "epub")
        assert ":" not in result
        assert "?" not in result
        assert "/" not in result

    def test_make_filename_truncates_long_names(self):
        """Test that long names are truncated."""
        long_title = "A" * 250
        result = _make_filename(long_title, "Author", "epub")
        # Should be truncated to ~200 chars + extension
        assert len(result) < 220

    def test_is_isbn_valid_isbn13(self):
        """Test ISBN-13 detection."""
        assert _is_isbn("9781234567890") is True

    def test_is_isbn_valid_isbn10(self):
        """Test ISBN-10 detection."""
        assert _is_isbn("1234567890") is True

    def test_is_isbn_with_hyphens(self):
        """Test ISBN with hyphens."""
        assert _is_isbn("978-1-234-56789-0") is True

    def test_is_isbn_invalid(self):
        """Test non-ISBN string."""
        assert _is_isbn("not an isbn") is False
        assert _is_isbn("12345") is False


class TestListCommand:
    """Tests for list command."""

    def test_list_empty_library(self):
        """Test listing empty library."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('bookcut.cli._download_dir', Path(tmpdir)):
                with patch('bookcut.cli._db') as mock_db:
                    mock_db.get_all_books.return_value = []

                    result = runner.invoke(app, ["list"])

                    assert "No books in library" in result.output


class TestGetCommand:
    """Tests for get command."""

    def test_get_shows_searching_message(self):
        """Test that get command shows searching message."""
        with patch('bookcut.cli.BookFinder') as MockFinder:
            mock_finder = MagicMock()
            mock_finder.__enter__ = MagicMock(return_value=mock_finder)
            mock_finder.__exit__ = MagicMock(return_value=False)
            mock_finder.find_book_and_download.return_value = (None, None)
            MockFinder.return_value = mock_finder

            result = runner.invoke(app, ["get", "test book"])

            assert "Searching for:" in result.output
            assert "test book" in result.output


class TestOpenCommand:
    """Tests for open command."""

    def test_open_nonexistent_book(self):
        """Test opening a book that doesn't exist."""
        with patch('bookcut.cli._db') as mock_db:
            mock_db.get_book.return_value = None
            mock_db.get_all_books.return_value = []

            result = runner.invoke(app, ["open", "nonexistent"])

            assert result.exit_code == 1
            assert "not found" in result.output.lower()


class TestRemoveCommand:
    """Tests for remove command."""

    def test_remove_nonexistent_book(self):
        """Test removing a book that doesn't exist."""
        with patch('bookcut.cli._db') as mock_db:
            mock_db.get_book.return_value = None

            result = runner.invoke(app, ["remove", "nonexistent"])

            assert result.exit_code == 1
            assert "not found" in result.output.lower()
