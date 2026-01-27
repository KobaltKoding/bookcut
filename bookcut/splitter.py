"""EPUB to Markdown splitter using epub2md."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class SplitterError(Exception):
    """Error during EPUB splitting."""
    pass


def check_epub2md_installed() -> bool:
    """Check if epub2md CLI is installed."""
    result = subprocess.run(
        ["which", "epub2md"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def split_epub_to_markdown(
    epub_path: Path,
    output_dir: Path,
    on_status=None,
) -> Path:
    """
    Convert EPUB to chapter-wise markdown files using epub2md.

    Args:
        epub_path: Path to the EPUB file
        output_dir: Base directory for markdown output (e.g., ~/BookCut/markdown/)
        on_status: Optional callback for status messages

    Returns:
        Path to the output folder containing markdown files

    Raises:
        SplitterError: If conversion fails
    """
    if not check_epub2md_installed():
        raise SplitterError(
            "epub2md is not installed. Install it with: npm install -g epub2md"
        )

    epub_path = Path(epub_path).resolve()

    if not epub_path.exists():
        raise SplitterError(f"EPUB file not found: {epub_path}")

    if epub_path.suffix.lower() != ".epub":
        raise SplitterError(f"Not an EPUB file: {epub_path}")

    # Create output directory
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # epub2md creates a folder named after the input file (without extension)
    # We'll use a sanitized version of the book name
    book_name = epub_path.stem
    final_output = output_dir / book_name

    # If output already exists, remove it for fresh conversion
    if final_output.exists():
        if on_status:
            on_status(f"Removing existing output: {final_output}")
        shutil.rmtree(final_output)

    # epub2md outputs to current working directory
    # So we copy epub to output_dir and run from there
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        tmp_epub = tmpdir / f"{book_name}.epub"

        if on_status:
            on_status(f"Preparing conversion...")

        shutil.copy2(epub_path, tmp_epub)

        if on_status:
            on_status(f"Converting {epub_path.name} to markdown...")

        # Run epub2md
        result = subprocess.run(
            ["epub2md", tmp_epub.name, "-c"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            raise SplitterError(f"epub2md failed: {error_msg}")

        # Move output to final location
        tmp_output = tmpdir / book_name
        if not tmp_output.exists():
            raise SplitterError(f"Conversion succeeded but output not found: {tmp_output}")

        shutil.move(str(tmp_output), str(final_output))

    # Count output files
    md_files = list(final_output.glob("*.md"))

    if on_status:
        on_status(f"Created {len(md_files)} markdown files in {final_output.name}/")

    return final_output


def list_chapters(markdown_dir: Path) -> list[dict]:
    """
    List all chapters in a markdown directory.

    Returns list of dicts with 'number', 'name', 'path', 'size' keys.
    """
    markdown_dir = Path(markdown_dir)

    if not markdown_dir.exists():
        return []

    chapters = []
    for md_file in sorted(markdown_dir.glob("*.md")):
        # Parse filename like "09-Capitolo_primo.md"
        name = md_file.stem
        parts = name.split("-", 1)

        if len(parts) == 2 and parts[0].isdigit():
            number = int(parts[0])
            chapter_name = parts[1].replace("_", " ")
        else:
            number = 0
            chapter_name = name

        chapters.append({
            "number": number,
            "name": chapter_name,
            "path": md_file,
            "size": md_file.stat().st_size,
        })

    return chapters
