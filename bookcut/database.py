"""SQLite database for local book library management."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LibraryBook:
    """A book in the local library."""

    md5: str
    title: str
    author: str
    format: str
    file_path: str
    publisher: str | None = None
    info: str | None = None
    description: str | None = None
    thumbnail: str | None = None
    isbn: str | None = None


class Database:
    """SQLite database for managing downloaded books."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path.home() / "BookCut" / "library.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    md5 TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    author TEXT,
                    format TEXT,
                    file_path TEXT,
                    publisher TEXT,
                    info TEXT,
                    description TEXT,
                    thumbnail TEXT,
                    isbn TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migration: add isbn column if it doesn't exist
            cursor = conn.execute("PRAGMA table_info(books)")
            columns = [row[1] for row in cursor.fetchall()]
            if "isbn" not in columns:
                conn.execute("ALTER TABLE books ADD COLUMN isbn TEXT")
            conn.commit()

    def add_book(self, book: LibraryBook) -> None:
        """Add a book to the library."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO books
                (md5, title, author, format, file_path, publisher, info, description, thumbnail, isbn)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book.md5,
                    book.title,
                    book.author,
                    book.format,
                    book.file_path,
                    book.publisher,
                    book.info,
                    book.description,
                    book.thumbnail,
                    book.isbn,
                ),
            )
            conn.commit()

    def get_book(self, md5: str) -> LibraryBook | None:
        """Get a book by MD5 hash."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM books WHERE md5 = ?", (md5,))
            row = cursor.fetchone()
            if row:
                return LibraryBook(
                    md5=row["md5"],
                    title=row["title"],
                    author=row["author"],
                    format=row["format"],
                    file_path=row["file_path"],
                    publisher=row["publisher"],
                    info=row["info"],
                    description=row["description"],
                    thumbnail=row["thumbnail"],
                    isbn=row["isbn"],
                )
        return None

    def get_all_books(self) -> list[LibraryBook]:
        """Get all books in the library."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM books ORDER BY created_at DESC"
            )
            return [
                LibraryBook(
                    md5=row["md5"],
                    title=row["title"],
                    author=row["author"],
                    format=row["format"],
                    file_path=row["file_path"],
                    publisher=row["publisher"],
                    info=row["info"],
                    description=row["description"],
                    thumbnail=row["thumbnail"],
                    isbn=row["isbn"],
                )
                for row in cursor.fetchall()
            ]

    def remove_book(self, md5: str) -> bool:
        """Remove a book from the library."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM books WHERE md5 = ?", (md5,))
            conn.commit()
            return cursor.rowcount > 0

    def book_exists(self, md5: str) -> bool:
        """Check if a book exists in the library."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM books WHERE md5 = ?", (md5,)
            )
            return cursor.fetchone() is not None

    def search_books(self, query: str) -> list[LibraryBook]:
        """Search books in library by title or author."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM books
                WHERE title LIKE ? OR author LIKE ?
                ORDER BY created_at DESC
                """,
                (f"%{query}%", f"%{query}%"),
            )
            return [
                LibraryBook(
                    md5=row["md5"],
                    title=row["title"],
                    author=row["author"],
                    format=row["format"],
                    file_path=row["file_path"],
                    publisher=row["publisher"],
                    info=row["info"],
                    description=row["description"],
                    thumbnail=row["thumbnail"],
                    isbn=row["isbn"],
                )
                for row in cursor.fetchall()
            ]
