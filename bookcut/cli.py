"""BookCut CLI interface."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from bookcut.database import Database, LibraryBook
from bookcut.sources import BookFinder, BookMetadata, DownloadableBook, sort_by_format
from bookcut.splitter import split_epub_to_markdown, list_chapters, SplitterError, UnsupportedStructureError

app = typer.Typer(
    name="bookcut",
    help="Search and download books from LibGen",
    no_args_is_help=True,
)
console = Console()

import os

env_dir = os.environ.get("BOOKCUT_DIR")
if env_dir:
    _download_dir = Path(env_dir)
else:
    _download_dir = Path.home() / "BookCut"

_download_dir.mkdir(exist_ok=True, parents=True)
_markdown_dir = _download_dir / "markdown"
_db = Database() # Database class now handles the path internaly based on env var or default


def _truncate(text: str | None, length: int = 40) -> str:
    if not text:
        return ""
    return text[:length] + "..." if len(text) > length else text


def _make_filename(title: str, author: str, fmt: str) -> str:
    """Create 'Title - Author.ext' with sanitized chars."""
    def sanitize(s: str) -> str:
        return re.sub(r'[/\\:*?"<>|]', "", s).strip()

    clean_title = sanitize(title)
    clean_author = sanitize(author)

    if clean_author and clean_author.lower() != "unknown":
        name = f"{clean_title} - {clean_author}"
    else:
        name = clean_title

    if len(name) > 200:
        name = name[:200].rsplit(" ", 1)[0]

    return f"{name}.{fmt}"


def _is_isbn(query: str) -> bool:
    """Check if query looks like an ISBN (10 or 13 digits, optional hyphens)."""
    digits = query.replace("-", "").replace(" ", "")
    return digits.isdigit() and len(digits) in (10, 13)


def _find_book_by_id(book_id: str) -> LibraryBook | None:
    """Find a book by exact or partial MD5 match."""
    book = _db.get_book(book_id)
    if book:
        return book

    all_books = _db.get_all_books()
    matches = [b for b in all_books if b.md5.startswith(book_id)]

    if len(matches) == 1:
        return matches[0]
    return None


def _save_to_library(
    metadata: BookMetadata,
    download: DownloadableBook,
    filepath: Path,
) -> str:
    """Save a downloaded book to the library DB. Returns the book ID."""
    book_id = download.isbn or metadata.isbn or hashlib.md5(metadata.title.encode()).hexdigest()

    library_book = LibraryBook(
        md5=book_id,
        title=download.title,
        author=download.author or metadata.author,
        format=download.format,
        file_path=str(filepath),
        publisher=metadata.publisher,
        info=download.format.upper(),
        description=metadata.description,
        thumbnail=metadata.cover_url,
        isbn=download.isbn or metadata.isbn,
    )
    _db.add_book(library_book)
    return book_id


def _display_chapters(entries: list[dict]) -> None:
    """Print a Rich table of chapter/section entries."""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Type", width=8)
    table.add_column("Name", width=50)
    table.add_column("Size", width=10)

    for ch in entries:
        size_kb = ch["size"] / 1024
        num_str = str(ch["number"]).zfill(2) if ch["number"] else "--"
        entry_type = ch.get("type", "chapter")
        table.add_row(
            num_str,
            entry_type.capitalize(),
            _truncate(ch["name"], 48),
            f"{size_kb:.1f} KB",
        )

    ch_count = sum(1 for e in entries if e.get("type") == "chapter")
    sec_count = sum(1 for e in entries if e.get("type") == "section")
    console.print(table)
    console.print(f"\n[dim]{ch_count} chapter(s), {sec_count} section(s)[/dim]\n")





# === Commands ===


@app.command()
def get(
    query: str = typer.Argument(..., help="Book title or ISBN"),
) -> None:
    """Download a book by name or ISBN using waterfall search."""
    console.print(f"\n[bold]Searching for:[/bold] {query}\n")

    def status_callback(msg: str):
        console.print(f"[dim]{msg}[/dim]")

    with BookFinder() as finder:
        try:
            metadata, download, filepath = finder.find_book_and_download(
                query,
                download_dir=_download_dir,
                on_status=status_callback,
            )
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

        if not metadata:
            console.print("[yellow]No book found matching your query.[/yellow]")
            raise typer.Exit(0)

        if not download or not filepath:
            console.print(f"\n[yellow]Found book but no download available:[/yellow]")
            console.print(f"  Title: {metadata.title}")
            console.print(f"  Author: {metadata.author or 'Unknown'}")
            if metadata.isbn:
                console.print(f"  ISBN: {metadata.isbn}")
            raise typer.Exit(1)

    _save_to_library(metadata, download, filepath)

    console.print(f"\n[green]Download complete![/green]")
    console.print(f"[dim]Saved to: {filepath}[/dim]\n")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    format: str = typer.Option("", "--format", "-f", help="Filter by format (epub, pdf)"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of results to show"),
) -> None:
    """Search for books."""
    console.print(f"\n[bold]Searching for:[/bold] {query}\n")

    with LibGenScraper() as scraper:
        try:
            books = scraper.search(query)
            if format:
                books = [b for b in books if b.info and format.lower() in b.info.lower()]
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    if not books:
        console.print("[yellow]No results found.[/yellow]")
        raise typer.Exit(0)

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", width=40)
    table.add_column("Author", width=20)
    table.add_column("Format", width=6)
    table.add_column("MD5", width=34)

    for i, book in enumerate(books[:limit], 1):
        fmt = "?"
        if book.info:
            for f in ("epub", "pdf", "cbr", "cbz", "mobi"):
                if f in book.info.lower():
                    fmt = f.upper()
                    break

        table.add_row(
            str(i),
            _truncate(book.title, 38),
            _truncate(book.author, 18),
            fmt,
            book.md5,
        )

    console.print(table)
    console.print(f"\n[dim]Showing {min(limit, len(books))} of {len(books)} results[/dim]")
    console.print("[dim]Use 'bookcut download <md5>' to download[/dim]\n")


@app.command()
def download(
    md5: str = typer.Argument(..., help="Book MD5 hash"),
) -> None:
    """Download a book from LibGen."""
    if _db.book_exists(md5):
        console.print("[yellow]Book already in library.[/yellow]")
        existing = _db.get_book(md5)
        if existing:
            console.print(f"[dim]File: {existing.file_path}[/dim]")
        raise typer.Exit(0)

    console.print(f"\n[bold]Fetching book info...[/bold]")

    with LibGenScraper() as scraper:
        try:
            book = scraper.get_book_info(md5)
        except Exception as e:
            console.print(f"[red]Error fetching book info:[/red] {e}")
            raise typer.Exit(1)

        if not book:
            console.print("[red]Book not found.[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]Title:[/bold] {book.title}")
        console.print(f"[bold]Author:[/bold] {book.author}")
        console.print(f"[bold]Format:[/bold] {book.format.upper()}\n")

        console.print("[dim]Getting download URL from LibGen...[/dim]")
        download_url = scraper.get_download_url(md5)

        if not download_url:
            console.print("[red]Could not get download URL.[/red]")
            raise typer.Exit(1)

        console.print("[dim]Downloading...[/dim]")
        filepath = _download_dir / f"{md5}.{book.format}"

        import builtins
        with scraper.client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            with builtins.open(filepath, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)

    library_book = LibraryBook(
        md5=book.md5,
        title=book.title,
        author=book.author,
        format=book.format,
        file_path=str(filepath),
        publisher=book.publisher,
        info=book.info,
        description=book.description,
        thumbnail=book.thumbnail,
    )
    _db.add_book(library_book)

    console.print(f"\n[green]Download complete![/green]")
    console.print(f"[dim]Saved to: {filepath}[/dim]\n")


@app.command("list")
def list_books(
    query: str = typer.Option("", "--search", "-s", help="Search in library"),
) -> None:
    """List books in your library."""
    if query:
        books = _db.search_books(query)
    else:
        books = _db.get_all_books()

    if not books:
        console.print("\n[yellow]No books in library.[/yellow]")
        console.print("[dim]Use 'bookcut search <query>' to find books[/dim]\n")
        raise typer.Exit(0)

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", width=45)
    table.add_column("Author", width=25)
    table.add_column("Format", width=8)
    table.add_column("MD5", width=12)

    for i, book in enumerate(books, 1):
        table.add_row(
            str(i),
            _truncate(book.title, 43),
            _truncate(book.author, 23),
            book.format.upper() if book.format else "?",
            book.md5[:10] + "...",
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(books)} book(s) in library[/dim]")
    console.print("[dim]Use 'bookcut open <md5>' to open a book[/dim]\n")


@app.command("open")
def open_book(
    md5: str = typer.Argument(..., help="Book MD5 hash"),
) -> None:
    """Open a downloaded book."""
    book = _db.get_book(md5)

    if not book:
        all_books = _db.get_all_books()
        matches = [b for b in all_books if b.md5.startswith(md5)]
        if len(matches) == 1:
            book = matches[0]
        elif len(matches) > 1:
            console.print("[yellow]Multiple matches found.[/yellow]")
            raise typer.Exit(1)
        else:
            console.print("[red]Book not found in library.[/red]")
            raise typer.Exit(1)

    filepath = Path(book.file_path)
    if not filepath.exists():
        console.print(f"[red]File not found:[/red] {filepath}")
        raise typer.Exit(1)

    console.print(f"[bold]Opening:[/bold] {book.title}")

    if sys.platform == "darwin":
        subprocess.run(["open", str(filepath)])
    elif sys.platform == "win32":
        subprocess.run(["start", str(filepath)], shell=True)
    else:
        subprocess.run(["xdg-open", str(filepath)])


@app.command()
def remove(
    md5: str = typer.Argument(..., help="Book MD5 hash"),
    keep_file: bool = typer.Option(False, "--keep-file", "-k", help="Keep the downloaded file"),
) -> None:
    """Remove a book from library."""
    book = _db.get_book(md5)

    if not book:
        console.print("[red]Book not found in library.[/red]")
        raise typer.Exit(1)

    if not keep_file:
        filepath = Path(book.file_path)
        if filepath.exists():
            filepath.unlink()
            console.print(f"[dim]Deleted: {filepath}[/dim]")

    _db.remove_book(md5)
    console.print(f"[green]Removed:[/green] {book.title}")


@app.command()
def split(
    book_id: str = typer.Argument(..., help="Book ID from library or path to EPUB file"),
) -> None:
    """Split an EPUB into chapter-wise markdown files."""
    if book_id.endswith(".epub") or "/" in book_id:
        epub_path = Path(book_id).expanduser().resolve()
        if not epub_path.exists():
            console.print(f"[red]File not found:[/red] {epub_path}")
            raise typer.Exit(1)
        book_title = epub_path.stem
    else:
        book = _find_book_by_id(book_id)
        if not book:
            all_books = _db.get_all_books()
            matches = [b for b in all_books if b.md5.startswith(book_id)]
            if len(matches) > 1:
                console.print("[yellow]Multiple matches found. Be more specific:[/yellow]")
                for b in matches:
                    console.print(f"  {b.md5[:10]}... - {b.title}")
                raise typer.Exit(1)
            console.print("[red]Book not found in library.[/red]")
            raise typer.Exit(1)

        epub_path = Path(book.file_path)
        book_title = book.title

        if not epub_path.exists():
            console.print(f"[red]File not found:[/red] {epub_path}")
            raise typer.Exit(1)

        if book.format and book.format.lower() != "epub":
            console.print(f"[red]Not an EPUB file:[/red] {book.format.upper()}")
            console.print("[dim]Only EPUB files can be split into markdown.[/dim]")
            raise typer.Exit(1)

    output_path = _do_split(epub_path, book_title)
    if output_path is None:
        raise typer.Exit(1)

    entries = list_chapters(output_path)

    console.print(f"\n[green]Split complete![/green]")
    console.print(f"[dim]Output: {output_path}[/dim]\n")
    _display_chapters(entries)


@app.command()
def chapters(
    book_id: str = typer.Argument(..., help="Book ID from library"),
) -> None:
    """List chapters for a split book."""
    book = _find_book_by_id(book_id)
    if not book:
        console.print("[red]Book not found in library.[/red]")
        raise typer.Exit(1)

    epub_path = Path(book.file_path)
    markdown_path = _markdown_dir / epub_path.stem

    if not markdown_path.exists():
        console.print(f"[yellow]Book has not been split yet.[/yellow]")
        console.print(f"[dim]Run: bookcut split {book_id}[/dim]")
        raise typer.Exit(1)

    entries = list_chapters(markdown_path)

    console.print(f"\n[bold]{book.title}[/bold]\n")
    _display_chapters(entries)
    console.print(f"[dim]{markdown_path}[/dim]")


@app.command()
def grab(
    query: str = typer.Argument(..., help="Book title or ISBN"),
) -> None:
    """Download a book and split it into chapter markdown files in one step."""
    console.print(f"\n[bold]Grabbing:[/bold] {query}\n")

    def status_callback(msg: str):
        console.print(f"[dim]{msg}[/dim]")

    from bookcut.lib import BookCutLib
    lib = BookCutLib(_download_dir, _db)
    
    metadata, epub_path, output_path = lib.grab_book(
        query, 
        on_status=status_callback,
        force_epub=True,
    )

    if not metadata:
        console.print("[yellow]No book found matching your query.[/yellow]")
        raise typer.Exit(0)

    if not epub_path:
        console.print(f"\n[yellow]Could not find an EPUB download for '{metadata.title}'.[/yellow]")
        console.print("[dim]Try 'bookcut get' to download in any format.[/dim]")
        raise typer.Exit(1)

    if output_path is None:
        console.print("[yellow]Split failed. The book was downloaded but could not be split.[/yellow]")
        raise typer.Exit(1)

    entries = list_chapters(output_path)

    console.print(f"\n[green]Done! Book downloaded and split.[/green]")
    console.print(f"[dim]EPUB: {epub_path}[/dim]")
    console.print(f"[dim]Chapters: {output_path}[/dim]\n")
    _display_chapters(entries)





if __name__ == "__main__":
    app()
