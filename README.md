# BookCut

A CLI tool to search, download, and split ebooks into chapter-wise markdown. Uses OpenLibrary and Google Books to find ISBNs, then searches LibGen for downloads. Prefers EPUB format.

## Installation

```bash
pip install bookcut
```

Or install from source:

```bash
git clone https://github.com/KobaltKoding/bookcut.git
cd bookcut
pip install -e .
```

For a global CLI install that automatically handles PATH:

```bash
pipx install .
```

### Fallback invocation

If the `bookcut` command isn't found after installation (e.g. `~/.local/bin` is not on your PATH), you can always run:

```bash
python -m bookcut
```

> **Tip:** Using a virtual environment (`python -m venv .venv && source .venv/bin/activate`) before `pip install -e .` avoids PATH issues entirely.

### Requirements

- Python 3.9+
- [epub2md](https://www.npmjs.com/package/epub2md) (for splitting EPUBs into markdown):

```bash
npm install -g epub2md
```

## Usage

### Grab a book (download + split in one step)

```bash
bookcut grab "Norwegian Wood"
bookcut grab "Sapiens"
```

This will:
1. Search for the book and collect ISBNs
2. Download an EPUB from LibGen
3. Split the EPUB into organized chapter markdown files
4. Display the chapter listing

### Download a book

```bash
bookcut get "The Cold Start Problem"
bookcut get "man who died twice richard osman"
```

Downloads any available format (EPUB preferred). If a download fails mid-stream, the waterfall retries with the next ISBN.

### Split an EPUB into chapters

```bash
bookcut split <book_id>
bookcut split ~/path/to/book.epub
```

Converts an EPUB to chapter-wise markdown files using epub2md, then classifies and organizes them:
- **Chapters**: Named `chapter_01_Title.md`, `chapter_02_Title.md`, etc.
- **Sections**: Non-chapter content (Introduction, Preface, Afterword) named `section_introduction.md`, etc.
- **Part headers**: Merged into the first chapter of each part
- **Discarded**: Cover, copyright, table of contents, index, etc.

If the EPUB has an unsupported structure, BookCut automatically tries downloading an alternate edition.

### List chapters

```bash
bookcut chapters <book_id>
```

### List your library

```bash
bookcut list
bookcut list -s "python"
```

### Open a book

```bash
bookcut open <id>
```

### Remove a book

```bash
bookcut remove <id>
```

## How it works

### Download Waterfall

1. **Metadata Search**: Queries OpenLibrary API and Google Books API to find book metadata and ISBNs
2. **ISBN Collection**: Gathers all unique ISBNs for different editions
3. **Download Search**: Tries each ISBN on LibGen until a matching download is found
4. **Retry on Failure**: If a download fails mid-stream (e.g. connection reset), tries the next ISBN
5. **Title Verification**: Ensures the found download matches the expected title
6. **Format Preference**: Prefers EPUB > MOBI > PDF when multiple formats available

### Chapter Detection

After epub2md converts an EPUB to raw markdown files, BookCut classifies each file by filename pattern:

| Pattern | Example | Books |
|---------|---------|-------|
| `Chapter_N__Title` | `Chapter_1__Don't_Try` | Subtle Art, Creativity Inc |
| `Chapter_N` | `Chapter_1` | Man Who Died Twice |
| `Chapter_Word` | `Chapter_One` | Stellarlune |
| `N._Title` | `1._An_Animal_of_No_Significance` | Sapiens |
| `N_Title` | `1_The_Challenge_of_the_Future` | Zero to One, Orchid & the Wasp |

Part headers are merged into the first chapter of each part. Unsupported fragmented structures (e.g. split files with no chapter markers) trigger an automatic re-download of an alternate edition.

## Library

Downloaded books are stored in `~/BookCut/` with a SQLite database tracking your library. Split markdown files are stored in `~/BookCut/markdown/<book_name>/`.

## License

MIT
