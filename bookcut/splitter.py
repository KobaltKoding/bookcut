"""EPUB to Markdown splitter using epub2md."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class SplitterError(Exception):
    """Error during EPUB splitting."""
    pass


class UnsupportedStructureError(SplitterError):
    """EPUB has a fragmented structure that can't be classified."""
    pass


# --- Classification patterns ---

_CHAPTER_PATTERNS = [
    # Chapter_N__Title or Chapter_N
    re.compile(r"^Chapter_\d+", re.IGNORECASE),
    # Chapter_Word (word numbers like Chapter_One, Chapter_Twenty_Three)
    re.compile(
        r"^Chapter_(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|"
        r"Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|"
        r"Eighteen|Nineteen|Twenty|Thirty|Forty|Fifty|Sixty|Seventy|"
        r"Eighty|Ninety|Hundred)",
        re.IGNORECASE,
    ),
    # N._Title (e.g. "1._An_Animal_of_No_Significance")
    re.compile(r"^\d+\._"),
    # N_Title (bare number, e.g. "1_The_Challenge_of_the_Future")
    re.compile(r"^\d+_[A-Z]"),
]

_PART_HEADER_PATTERNS = [
    re.compile(r"^Part_", re.IGNORECASE),
    re.compile(r"^PART_"),
]

_CONTENT_SECTION_NAMES = {
    "introduction", "preface", "foreword", "prologue",
    "afterword", "epilogue", "postscriptum",
    "conclusion", "timeline", "glossary",
}

_DISCARD_NAMES = {
    "cover", "title_page", "title", "halftitle", "nav",
    "contents", "toc",
    "copyright",
    "about_the_author", "about_the_authors", "about_the_publisher",
    "about_the_book",
    "acknowledgments", "acknowledgements", "credits",
    "illustration_credits",
    "praise", "dedication", "epigraph",
    "index", "notes",
    "photo_insert", "ss_recommendpage", "ba1", "backcover",
}

_DISCARD_PATTERNS = [
    re.compile(r"^dedication\d*$", re.IGNORECASE),
    re.compile(r"^\d{10,}"),  # ISBN-prefixed junk
    re.compile(r"^part\d{4}$"),  # Generic partNNNN
    re.compile(r"^part\d{4}_split_\d+$"),  # partNNNN_split_NNN
    # Author_Name_-_Book_Title_split_NNN (fragmented epubs)
    re.compile(r"_split_\d+$"),
]


def _parse_raw_filename(filename: str) -> tuple[int, str]:
    """Parse '09-Chapter_Name.md' into (9, 'Chapter_Name')."""
    stem = Path(filename).stem
    parts = stem.split("-", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), parts[1]
    return 0, stem


def _classify(name: str, file_size: int) -> str:
    """Classify a file by its name (without number prefix).

    Returns one of: 'chapter', 'part_header', 'section', 'discard', 'unknown'.
    """
    lower = name.lower()

    # Check discard first (exact match)
    if lower in _DISCARD_NAMES:
        return "discard"

    # Check discard patterns
    for pat in _DISCARD_PATTERNS:
        if pat.search(name):
            return "discard"

    # Check chapter patterns
    for pat in _CHAPTER_PATTERNS:
        if pat.match(name):
            return "chapter"

    # Check part headers
    for pat in _PART_HEADER_PATTERNS:
        if pat.match(name):
            return "part_header"

    # Check content sections (partial match at start, after optional __)
    # Handles "Introduction__Lost_and_Found", "Preface__Zero_to_One", "Conclusion__Title"
    base = lower.split("__")[0]
    if base in _CONTENT_SECTION_NAMES:
        return "section"

    return "unknown"


def _extract_chapter_title(name: str) -> str:
    """Extract a clean chapter title from the raw filename part."""
    # Chapter_N__Title → Title
    m = re.match(r"^Chapter_\w+__(.+)$", name, re.IGNORECASE)
    if m:
        return m.group(1).replace("_", " ")

    # Chapter_N → Chapter N
    m = re.match(r"^Chapter_(\d+)$", name, re.IGNORECASE)
    if m:
        return f"Chapter {m.group(1)}"

    # Chapter_Word → Chapter Word
    m = re.match(r"^Chapter_([A-Za-z_]+)$", name, re.IGNORECASE)
    if m:
        return f"Chapter {m.group(1).replace('_', ' ')}"

    # N._Title → Title
    m = re.match(r"^\d+\._(.+)$", name)
    if m:
        return m.group(1).replace("_", " ")

    # N_Title → Title
    m = re.match(r"^\d+_(.+)$", name)
    if m:
        return m.group(1).replace("_", " ")

    return name.replace("_", " ")


def _extract_section_title(name: str) -> str:
    """Extract clean section title. 'Introduction__Lost_and_Found' → 'Introduction - Lost and Found'."""
    parts = name.split("__", 1)
    base = parts[0].replace("_", " ")
    if len(parts) == 2:
        subtitle = parts[1].replace("_", " ")
        return f"{base} - {subtitle}"
    return base


def classify_and_organize(
    raw_dir: Path,
    output_dir: Path,
    on_status=None,
) -> Path:
    """Classify raw epub2md files and write organized chapter/section files.

    Returns output_dir. Raises UnsupportedStructureError if structure is unrecognizable.
    """
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse and classify all files
    raw_files = sorted(raw_dir.glob("*.md"))
    if not raw_files:
        raise SplitterError(f"No markdown files found in {raw_dir}")

    classified = []
    for f in raw_files:
        num, name = _parse_raw_filename(f.name)
        kind = _classify(name, f.stat().st_size)
        classified.append({
            "path": f,
            "num": num,
            "name": name,
            "kind": kind,
            "size": f.stat().st_size,
        })

    # Check for unsupported structure
    chapters = [c for c in classified if c["kind"] == "chapter"]
    sections = [c for c in classified if c["kind"] == "section"]
    unknowns = [c for c in classified if c["kind"] == "unknown"]

    if len(chapters) == 0 and len(unknowns) > 5:
        split_files = [c for c in unknowns if "_split_" in c["name"]]
        if len(split_files) > len(unknowns) // 2:
            raise UnsupportedStructureError(
                "This EPUB has a fragmented structure that cannot be automatically classified. "
                "Try downloading a different edition of this book."
            )

    if len(chapters) == 0 and len(sections) == 0:
        raise UnsupportedStructureError(
            "No chapters or sections detected in the EPUB output."
        )

    # Build output by walking in order
    part_buffer = ""
    chapter_num = 0
    written = []

    for entry in classified:
        kind = entry["kind"]

        if kind == "discard":
            continue

        if kind == "part_header":
            content = entry["path"].read_text(encoding="utf-8", errors="replace")
            part_buffer += content + "\n\n"
            continue

        if kind == "unknown":
            # Small unknown files after a part header → merge into part buffer
            if part_buffer and entry["size"] < 1024:
                content = entry["path"].read_text(encoding="utf-8", errors="replace")
                part_buffer += content + "\n\n"
                continue
            # Otherwise skip
            continue

        if kind == "chapter":
            chapter_num += 1
            title = _extract_chapter_title(entry["name"])
            safe_title = re.sub(r'[/\\:*?"<>|]', "", title).strip()
            safe_title = safe_title.replace(" ", "_")
            if len(safe_title) > 80:
                safe_title = safe_title[:80].rsplit("_", 1)[0]

            out_name = f"chapter_{chapter_num:02d}_{safe_title}.md"
            content = entry["path"].read_text(encoding="utf-8", errors="replace")

            if part_buffer:
                content = part_buffer + content
                part_buffer = ""

            out_path = output_dir / out_name
            out_path.write_text(content, encoding="utf-8")
            written.append(("chapter", chapter_num, out_name))
            continue

        if kind == "section":
            title = _extract_section_title(entry["name"])
            safe_title = re.sub(r'[/\\:*?"<>|]', "", title).strip()
            safe_title = safe_title.replace(" ", "_").lower()

            out_name = f"section_{safe_title}.md"
            content = entry["path"].read_text(encoding="utf-8", errors="replace")
            out_path = output_dir / out_name
            out_path.write_text(content, encoding="utf-8")
            written.append(("section", 0, out_name))
            continue

    if on_status:
        ch_count = sum(1 for w in written if w[0] == "chapter")
        sec_count = sum(1 for w in written if w[0] == "section")
        on_status(f"Organized: {ch_count} chapters, {sec_count} sections")

    return output_dir


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
    """Convert EPUB to organized chapter-wise markdown files.

    Runs epub2md then classifies and organizes the output.

    Returns:
        Path to the output folder containing organized markdown files.

    Raises:
        SplitterError: If conversion fails.
        UnsupportedStructureError: If epub structure can't be classified.
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

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    book_name = epub_path.stem
    final_output = output_dir / book_name

    if final_output.exists():
        if on_status:
            on_status(f"Removing existing output: {final_output}")
        shutil.rmtree(final_output)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        tmp_epub = tmpdir / f"{book_name}.epub"

        if on_status:
            on_status("Preparing conversion...")

        shutil.copy2(epub_path, tmp_epub)

        if on_status:
            on_status(f"Converting {epub_path.name} to markdown...")

        result = subprocess.run(
            ["epub2md", tmp_epub.name, "-c"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            raise SplitterError(f"epub2md failed: {error_msg}")

        raw_output = tmpdir / book_name
        if not raw_output.exists():
            raise SplitterError(f"Conversion succeeded but output not found: {raw_output}")

        raw_md_count = len(list(raw_output.glob("*.md")))
        if on_status:
            on_status(f"epub2md created {raw_md_count} raw files, classifying...")

        final_output.mkdir(parents=True, exist_ok=True)
        classify_and_organize(raw_output, final_output, on_status=on_status)

    return final_output


def list_chapters(markdown_dir: Path) -> list[dict]:
    """List all chapters and sections in an organized markdown directory.

    Returns list of dicts with 'number', 'name', 'path', 'size', 'type' keys.
    'type' is 'chapter' or 'section'.
    """
    markdown_dir = Path(markdown_dir)

    if not markdown_dir.exists():
        return []

    entries = []
    for md_file in sorted(markdown_dir.glob("*.md")):
        name = md_file.stem
        size = md_file.stat().st_size

        if name.startswith("chapter_"):
            m = re.match(r"^chapter_(\d+)_(.+)$", name)
            if m:
                number = int(m.group(1))
                chapter_name = m.group(2).replace("_", " ")
            else:
                number = 0
                chapter_name = name.replace("_", " ")
            entries.append({
                "number": number,
                "name": chapter_name,
                "path": md_file,
                "size": size,
                "type": "chapter",
            })
        elif name.startswith("section_"):
            section_name = name[8:].replace("_", " ").title()
            entries.append({
                "number": 0,
                "name": f"[{section_name}]",
                "path": md_file,
                "size": size,
                "type": "section",
            })

    return entries
