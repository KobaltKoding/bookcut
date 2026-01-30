"""Shared logic for BookCut CLI and API."""

from __future__ import annotations

import shutil
import hashlib
from pathlib import Path
from typing import Optional, Callable, Any

from bookcut.database import Database, LibraryBook
from bookcut.sources import BookFinder, BookMetadata, DownloadableBook, sort_by_format, download_file
from bookcut.splitter import split_epub_to_markdown, SplitterError, UnsupportedStructureError

# Callback type
StatusCallback = Callable[[str], None]

def noop_status(msg: str):
    pass

class BookCutLib:
    def __init__(self, download_dir: Path, db: Database):
        self.download_dir = download_dir
        self.markdown_dir = download_dir / "markdown"
        self.db = db
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

    def _save_to_library(
        self,
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
        self.db.add_book(library_book)
        return book_id

    def retry_split_with_alternate_epub(
        self,
        book_title: str,
        failed_epub_path: Path,
        on_status: StatusCallback = noop_status,
        max_retries: int = 3,
        custom_markdown_dir: Optional[Path] = None,
    ) -> Path | None:
        """Try downloading alternate EPUB editions and splitting them."""
        output_dir = custom_markdown_dir or self.markdown_dir
        
        on_status(f"Searching for alternate EPUB editions of '{book_title}'...")

        with BookFinder() as finder:
            metadata, isbns = finder.collect_isbns(book_title, on_status=on_status)

            if not metadata:
                return None

            attempts = 0
            for i, isbn in enumerate(isbns):
                if attempts >= max_retries:
                    on_status(f"Exhausted {max_retries} retry attempts.")
                    break

                on_status(f"Trying ISBN {i+1}/{len(isbns)}: {isbn}")

                dl = finder.find_download_by_isbn(isbn, expected_title=metadata.title, on_status=on_status)
                if not dl or dl.format.lower() != "epub":
                    continue

                # Download to a temp file
                alt_epub = self.download_dir / f"_alt_{isbn}.epub"
                on_status(f"  Downloading alternate EPUB...")
                success = download_file(dl.download_url, alt_epub, on_status)
                if not success:
                    continue

                # Skip if same file size as the failed one
                if (failed_epub_path.exists() and alt_epub.exists()
                        and alt_epub.stat().st_size == failed_epub_path.stat().st_size):
                    on_status("  Same file as original, skipping...")
                    alt_epub.unlink()
                    continue

                attempts += 1
                on_status(f"  Attempting split (retry {attempts}/{max_retries})...")

                try:
                    # Pass the output directory logic carefully
                    # split_epub_to_markdown creates a subdir inside the output_dir
                    output_path = split_epub_to_markdown(
                        alt_epub,
                        output_dir,
                        on_status=on_status,
                    )
                    # Success — clean up the alt epub
                    alt_epub.unlink(missing_ok=True)

                    # For standard library usage, we might want to move it to standard location
                    # But if custom_markdown_dir is set (e.g. for /grab API), we leave it there.
                    
                    # Ensure consistency with original failed path if we are in main library mode
                    if custom_markdown_dir is None:
                         expected_output = self.markdown_dir / failed_epub_path.stem
                         if output_path != expected_output and output_path.exists():
                            if expected_output.exists():
                                shutil.rmtree(expected_output)
                            shutil.move(str(output_path), str(expected_output))
                            output_path = expected_output

                    return output_path
                except UnsupportedStructureError:
                    on_status("  This edition also has unsupported structure.")
                    alt_epub.unlink(missing_ok=True)
                    # Clean up failed output
                    alt_output = output_dir / alt_epub.stem
                    if alt_output.exists():
                        shutil.rmtree(alt_output)
                    continue
                except SplitterError as e:
                    on_status(f"  Split failed: {e}")
                    alt_epub.unlink(missing_ok=True)
                    continue

        return None

    def grab_book(
        self,
        query: str,
        on_status: StatusCallback = noop_status,
        force_epub: bool = True,
        custom_download_dir: Optional[Path] = None, # For temporary downloads
        skip_library_save: bool = False
    ) -> tuple[BookMetadata | None, Path | None, Path | None]:
        """
        Download and split a book.
        Returns (metadata, epub_path, split_output_path).
        """
        target_dir = custom_download_dir or self.download_dir
        
        # --- Phase 1: Download EPUB ---
        on_status("[bold]Phase 1: Downloading EPUB...[/bold]\n")

        with BookFinder() as finder:
            metadata, isbns = finder.collect_isbns(query, on_status=on_status)

            if not metadata:
                return None, None, None

            on_status(f"\nFound book: {metadata.title}")
            if metadata.author:
                on_status(f"Author: {metadata.author}")

            # Try to find and download an EPUB specifically
            epub_download = None
            epub_filepath = None

            if isbns:
                on_status(f"\nTrying {len(isbns)} ISBN(s) for EPUB download...")

                for i, isbn in enumerate(isbns):
                    on_status(f"Trying ISBN {i+1}/{len(isbns)}: {isbn}")

                    dl = finder.find_download_by_isbn(isbn, expected_title=metadata.title, on_status=on_status)
                    if not dl:
                        continue

                    # Prefer EPUB
                    if force_epub and dl.format.lower() != "epub":
                        # Check if there are epub alternatives for this ISBN
                        all_downloads = []
                        for source in finder.download_sources:
                            try:
                                all_downloads.extend(source.find_download(isbn))
                            except Exception:
                                continue
                        epub_options = [d for d in sort_by_format(all_downloads)
                                       if d.format.lower() == "epub"]
                        if epub_options:
                            dl = epub_options[0]
                            on_status(f"  Found EPUB version!")
                        else:
                            on_status(f"  Only {dl.format.upper()} available, skipping (need EPUB for split)...")
                            continue

                    dl.isbn = isbn

                    filepath = finder._attempt_download(dl, metadata, target_dir, on_status=on_status)
                    if filepath:
                        epub_download = dl
                        epub_filepath = filepath
                        break
                    else:
                        on_status("  Download failed, trying next ISBN...")

            # Fallback: title search
            if not epub_filepath:
                on_status("\nFalling back to title search...")
                dl = finder.find_download_by_title(metadata.title, metadata.author, on_status=on_status)
                if dl and dl.format.lower() == "epub":
                    filepath = finder._attempt_download(dl, metadata, target_dir, on_status=on_status)
                    if filepath:
                        epub_download = dl
                        epub_filepath = filepath

        if not epub_download or not epub_filepath:
            return metadata, None, None

        # Save to library if not skipped
        if not skip_library_save:
             self._save_to_library(metadata, epub_download, epub_filepath)

        on_status(f"\n[green]Download complete![/green]")
        on_status(f"[dim]Saved to: {epub_filepath}[/dim]\n")

        # --- Phase 2: Split ---
        on_status("[bold]Phase 2: Splitting into chapters...[/bold]\n")

        # Determine output dir for split
        if custom_download_dir:
             # If using custom dir (e.g. for API), allow splitter to create its own subdir
             split_base_dir = custom_download_dir / "chapters"
        else:
             split_base_dir = self.markdown_dir

        output_path = self._do_split(
            epub_filepath, 
            metadata.title, 
            on_status, 
            custom_output_dir=split_base_dir
        )
        
        return metadata, epub_filepath, output_path

    def _do_split(
        self, 
        epub_path: Path, 
        book_title: str, 
        on_status: StatusCallback,
        custom_output_dir: Path
    ) -> Path | None:
        """Attempt to split an EPUB, retrying with alternate editions on unsupported structure."""
        try:
            return split_epub_to_markdown(
                epub_path,
                custom_output_dir,
                on_status=on_status,
            )
        except (UnsupportedStructureError, SplitterError) as e:
            on_status(f"\n[yellow]Split failed ({str(e)}). Trying alternate editions...[/yellow]\n")
            
            # For retry, we need to pass the custom_output_dir if set
            result = self.retry_split_with_alternate_epub(
                book_title, 
                epub_path, 
                on_status, 
                custom_markdown_dir=custom_output_dir
            )
            if result is None:
                on_status("[red]Could not find a compatible EPUB edition.[/red]")
            return result
