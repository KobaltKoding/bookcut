# BookCut

A CLI tool to search and download ebooks. Uses OpenLibrary and Google Books to find ISBNs, then searches LibGen for downloads. Prefers EPUB format.

## Installation

```bash
pip install bookcut
```

Or install from source:

```bash
git clone https://github.com/kartikkaria/bookcut.git
cd bookcut
pip install -e .
```

## Usage

### Download a book

```bash
bookcut get "The Cold Start Problem"
bookcut get "man who died twice richard osman"
```

The tool will:
1. Search OpenLibrary and Google Books for the book
2. Collect all available ISBNs
3. Try each ISBN on LibGen until a download is found
4. Prefer EPUB format over other formats
5. Save to `~/BookCut/`

### List your library

```bash
bookcut list
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

BookCut uses a waterfall approach:

1. **Metadata Search**: Queries OpenLibrary API and Google Books API to find book metadata and ISBNs
2. **ISBN Collection**: Gathers all unique ISBNs for different editions
3. **Download Search**: Tries each ISBN on LibGen until a matching download is found
4. **Title Verification**: Ensures the found download matches the expected title
5. **Format Preference**: Prefers EPUB > MOBI > PDF when multiple formats available

## Library

Downloaded books are stored in `~/BookCut/` with a SQLite database tracking your library.

## License

MIT
