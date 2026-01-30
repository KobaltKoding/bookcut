from datetime import datetime
import os
import hashlib
import shutil
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Body, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

from bookcut.database import Database, LibraryBook
from bookcut.sources import BookFinder
from bookcut.splitter import split_epub_to_markdown, list_chapters, UnsupportedStructureError

app = FastAPI(title="BookCut API")

# --- Config ---
env_dir = os.environ.get("BOOKCUT_DIR")
if env_dir:
    DOWNLOAD_DIR = Path(env_dir)
else:
    DOWNLOAD_DIR = Path.home() / "BookCut"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
MARKDOWN_DIR = DOWNLOAD_DIR / "markdown"
MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

db = Database()

# --- Models ---
class BookResponse(BaseModel):
    md5: str
    title: str
    author: Optional[str] = None
    format: Optional[str] = None
    publisher: Optional[str] = None
    info: Optional[str] = None
    isbn: Optional[str] = None

class SearchResult(BaseModel):
    title: str
    author: Optional[str] = None
    year: Optional[str] = None
    isbn: Optional[str] = None
    md5: Optional[str] = None # Some MD5s might be available in search results

class DownloadRequest(BaseModel):
    query: Optional[str] = None
    md5: Optional[str] = None

class ChapterEntry(BaseModel):
    number: int
    name: str
    type: str # 'chapter' or 'section'
    size: int

# --- Routes ---

@app.get("/")
def read_root():
    return {"status": "ok", "service": "BookCut API"}

@app.get("/library", response_model=List[BookResponse])
def get_library():
    try:
        books = db.get_all_books()
        return [
            BookResponse(
                md5=b.md5,
                title=b.title,
                author=b.author,
                format=b.format,
                publisher=b.publisher,
                info=b.info,
                isbn=b.isbn
            ) for b in books
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search", response_model=List[SearchResult])
def search_books(q: str):
    if not q:
        return []
    
    results = []
    # Use BookFinder to search metadata
    # For now, let's expose just the metadata search from openlibrary/google
    # We could also use LibGenScraper for direct download links but that's slower
    
    # Re-using BookFinder logic partially?
    # BookFinder.collect_isbns does the search
    
    # Let's use the sources directly for a quicker search response if possible, 
    # or just use BookFinder to get metadata.
    
    with BookFinder() as finder:
        # We can use the finder's sources
        for source in finder.search_sources:
            try:
                found = source.search(q, limit=5)
                for f in found:
                    results.append(SearchResult(
                        title=f.title,
                        author=f.author,
                        year=f.year,
                        isbn=f.isbn
                    ))
            except Exception:
                continue
    return results

def _background_download(query: str, md5: Optional[str]):
    # This function would be better if it could update some state
    # For now, it just runs. In a real app we'd track job status.
    print(f"Starting background download for {query or md5}")
    with BookFinder() as finder:
        try:
             # Logic similar to cli.get
             # If md5 provided, we need a way to download by md5 directly via scraper
             # But finder.find_book_and_download expects query.
             # If we have MD5, we should probably use LibGenScraper directly?
             # For V1 let's stick to query-based or basic find_book_and_download
             
             # If MD5 is given, we need to implement md5 download in BookFinder or expose Scraper
             # The CLI 'download' command uses LibGenScraper directly.
             pass 
        except Exception as e:
            print(f"Download failed: {e}")

@app.post("/download")
def download_book(req: DownloadRequest):
    if not req.query and not req.md5:
         raise HTTPException(status_code=400, detail="Query or MD5 required")

    # For V1, let's run synchronously to be simple and return result
    # (As discussed in implementation plan, sync is okay for V1)
    
    if req.md5:
        # Check if already exists
        if db.book_exists(req.md5):
             book = db.get_book(req.md5)
             return {"status": "exists", "book_id": book.md5, "title": book.title}
        
        from bookcut.scraper import LibGenScraper
        
        # We need to implement the download logic similar to cli.download
        # Since logic isn't fully reusable from a single function, I will copy-paste simplified logic
        # OR refactor. For now, copy-paste simplified.
        
        try:
            with LibGenScraper() as scraper:
                info = scraper.get_book_info(req.md5)
                if not info:
                     raise HTTPException(status_code=404, detail="Book not found by MD5")
                
                url = scraper.get_download_url(req.md5)
                if not url:
                     raise HTTPException(status_code=404, detail="Download link not found")
                
                filepath = DOWNLOAD_DIR / f"{req.md5}.{info.format}"
                import httpx
                # direct download
                with httpx.stream("GET", url, follow_redirects=True) as resp:
                     resp.raise_for_status()
                     with open(filepath, "wb") as f:
                         for chunk in resp.iter_bytes():
                             f.write(chunk)
                
                # Save to DB
                library_book = LibraryBook(
                    md5=info.md5,
                    title=info.title,
                    author=info.author,
                    format=info.format,
                    file_path=str(filepath),
                    publisher=info.publisher,
                    info=info.info,
                    description=info.description,
                    thumbnail=info.thumbnail
                )
                db.add_book(library_book)
                return {"status": "downloaded", "book_id": info.md5, "title": info.title}

        except Exception as e:
             raise HTTPException(status_code=500, detail=str(e))
             
    elif req.query:
         # Waterfall download
         with BookFinder() as finder:
             try:
                 # We need a status callback even if dummy
                 def noop(s): pass
                 metadata, download, filepath = finder.find_book_and_download(
                     req.query,
                     download_dir=DOWNLOAD_DIR,
                     on_status=noop
                 )
                 
                 if not metadata:
                      raise HTTPException(status_code=404, detail="No metadata found")
                 if not download or not filepath:
                      raise HTTPException(status_code=404, detail="Book found but download failed")
                 
                 # Save to DB - calculate ID if not present
                 # Database.add_book expects a LibraryBook
                 
                 # Refactor: _save_to_library logic from CLI is useful here.
                 # I'll re-implement it briefly.
                 
                 book_id = download.isbn or metadata.isbn or hashlib.md5(metadata.title.encode()).hexdigest()
                 
                 lb = LibraryBook(
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
                 db.add_book(lb)
                 return {"status": "downloaded", "book_id": book_id, "title": lb.title}

             except Exception as e:
                 raise HTTPException(status_code=500, detail=str(e))

@app.post("/split/{book_id}")
def split_book(book_id: str):
    book = db.get_book(book_id)
    if not book:
        # Try generic search in DB if partial match
        all_books = db.get_all_books()
        matches = [b for b in all_books if b.md5.startswith(book_id)]
        if len(matches) == 1:
            book = matches[0]
        else:
            raise HTTPException(status_code=404, detail="Book not found")
            
    epub_path = Path(book.file_path)
    if not epub_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
        
    if book.format.lower() != "epub":
        raise HTTPException(status_code=400, detail="Only EPUBs can be split")

    try:
        # Assuming we can reuse _do_split logic or call split_epub_to_markdown directly
        # The CLI's _do_split handles retries which is nice.
        # For endpoints, let's keep it simple: just call splitter.
        
        output_path = split_epub_to_markdown(epub_path, MARKDOWN_DIR)
        entries = list_chapters(output_path)
        
        return {
            "status": "split_complete",
            "chapters": [
                ChapterEntry(
                    number=e["number"],
                    name=e["name"],
                    type=e["type"],
                    size=e["size"]
                ) for e in entries
            ]
        }
    except UnsupportedStructureError:
        raise HTTPException(status_code=400, detail="Unsupported EPUB structure")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/grab")
def grab_book(req: DownloadRequest, background_tasks: BackgroundTasks):
    """Download, split, and return a zip of the book chapters."""
    if not req.query:
        raise HTTPException(status_code=400, detail="Query required for grab")

    # Tracking paths for cleanup
    temp_dirs = []
    
    def cleanup_files():
        for p in temp_dirs:
            if p.exists():
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()

    try:
        from bookcut.lib import BookCutLib
        lib = BookCutLib(DOWNLOAD_DIR, db)
        
        # Create a specific temp dir for this request
        import tempfile
        request_id = hashlib.md5((req.query + str(datetime.now())).encode()).hexdigest()[:8]
        req_dir = DOWNLOAD_DIR / f"grab_{request_id}"
        req_dir.mkdir(exist_ok=True)
        temp_dirs.append(req_dir)

        # Use BookCutLib
        metadata, epub_path, output_path = lib.grab_book(
            req.query,
            on_status=print, 
            force_epub=True,
            custom_download_dir=req_dir,
            skip_library_save=True
        )
        
        if not metadata:
             raise HTTPException(status_code=404, detail="Book not found")
             
        if not epub_path:
             cleanup_files()
             raise HTTPException(status_code=404, detail="Could not find an SPLITTABLE EPUB version of this book.")
             
        if not output_path:
             cleanup_files()
             raise HTTPException(status_code=500, detail="Split failed (and retries exhausted).")

        # 3. Zip
        zip_base_name = req_dir / "result"
        if output_path.is_dir():
             zip_path = shutil.make_archive(str(zip_base_name), 'zip', output_path)
        else:
             cleanup_files()
             raise HTTPException(status_code=500, detail="Unexpected split output format")
             
        temp_dirs.append(Path(zip_path))
        
        # 4. Return
        filename = f"{metadata.title}_chapters.zip"
        filename = "".join([c for c in filename if c.isalpha() or c.isdigit() or c in (' ', '.', '_')]).strip()
        
        background_tasks.add_task(cleanup_files)
        
        return FileResponse(zip_path, filename=filename, media_type="application/zip")

    except HTTPException:
        cleanup_files()
        raise
    except Exception as e:
        cleanup_files()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files/{book_id}")
def get_book_file(book_id: str):
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    path = Path(book.file_path)
    if not path.exists():
         raise HTTPException(status_code=404, detail="File missing")
         
    return FileResponse(path, filename=path.name)
