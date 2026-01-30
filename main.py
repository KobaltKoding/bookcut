from datetime import datetime
import os
import hashlib
import shutil
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Body, BackgroundTasks, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from bookcut.database import Database, LibraryBook
from bookcut.jobs import JobStore, JobStatus
from bookcut.sources import BookFinder
from bookcut.splitter import split_epub_to_markdown, list_chapters, UnsupportedStructureError

app = FastAPI(title="BookCut API")

# Single global job store (in-memory)
job_store = JobStore()

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


def process_grab_job(job_id: str, query: str, force_epub: bool = True):
    """Background task to run the grab pipeline and update job status."""
    import shutil
    
    try:
        job_store.update_status(job_id, JobStatus.PROCESSING, "Starting download process...")

        # Create temp dir
        request_id = hashlib.md5((query + str(datetime.now())).encode()).hexdigest()[:8]
        req_dir = DOWNLOAD_DIR / f"grab_{request_id}"
        req_dir.mkdir(exist_ok=True)
        
        # Status callback to update job log
        def status_callback(msg):
             job_store.append_log(job_id, msg)
             print(f"[{job_id}] {msg}")

        from bookcut.lib import BookCutLib
        lib = BookCutLib(DOWNLOAD_DIR, db)
        
        metadata, epub_path, output_path = lib.grab_book(
            query,
            on_status=status_callback,
            force_epub=force_epub,
            custom_download_dir=req_dir,
            skip_library_save=True
        )

        if not metadata:
             job_store.fail_job(job_id, "Book not found")
             shutil.rmtree(req_dir)
             return

        if not epub_path:
             job_store.fail_job(job_id, "Could not find a splittable EPUB version.")
             shutil.rmtree(req_dir)
             return

        if not output_path:
             job_store.fail_job(job_id, "Split failed (and retries exhausted).")
             shutil.rmtree(req_dir)
             return
             
        # Zip result
        job_store.update_status(job_id, JobStatus.PROCESSING, "Zipping result...")
        zip_base_name = req_dir / "result"
        if output_path.is_dir():
             zip_path = shutil.make_archive(str(zip_base_name), 'zip', output_path)
        else:
             job_store.fail_job(job_id, "Unexpected split output format")
             shutil.rmtree(req_dir)
             return

        # Keep zip, complete job
        job_store.complete_job(job_id, zip_path)
        
    except Exception as e:
        job_store.fail_job(job_id, str(e))
        if 'req_dir' in locals() and req_dir.exists():
            shutil.rmtree(req_dir)

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


def process_split_job(job_id: str, epub_path: Path, original_filename: str):
    """Background task to split an uploaded EPUB and update job status."""
    import shutil
    import tempfile
    
    try:
        job_store.update_status(job_id, JobStatus.PROCESSING, "Starting split process...")
        
        # Status callback
        def status_callback(msg):
             job_store.append_log(job_id, msg)
             print(f"[{job_id}] {msg}")

        # Create output dir (sibiling to the epub file or a new temp dir)
        # epub_path is likely in a temp dir already created in the endpoint
        req_dir = epub_path.parent
        
        job_store.update_status(job_id, JobStatus.PROCESSING, "Splitting into chapters...")
        
        try:
             # We can use split_epub_to_markdown directly
             output_path = split_epub_to_markdown(
                 epub_path,
                 req_dir, # Output to same temp dir
                 on_status=status_callback
             )
        except Exception as e:
             job_store.fail_job(job_id, f"Split failed: {e}")
             if req_dir.exists():
                 shutil.rmtree(req_dir)
             return

        # Zip result
        job_store.update_status(job_id, JobStatus.PROCESSING, "Zipping result...")
        
        safe_name = "".join([c for c in original_filename if c.isalpha() or c.isdigit() or c in (' ', '.', '_')]).strip()
        zip_base_name = req_dir / f"{safe_name}_chapters"
        
        if output_path.is_dir():
             zip_path = shutil.make_archive(str(zip_base_name), 'zip', output_path)
        else:
             job_store.fail_job(job_id, "Unexpected split output format")
             shutil.rmtree(req_dir)
             return

        # Complete job
        job_store.complete_job(job_id, zip_path)
        
    except Exception as e:
        job_store.fail_job(job_id, str(e))
        if 'req_dir' in locals() and req_dir.exists():
            shutil.rmtree(req_dir)


@app.post("/split-file")
def split_file(file: UploadFile, background_tasks: BackgroundTasks):
    """Upload an EPUB file to split asynchronously."""
    if not file.filename.lower().endswith(".epub"):
         raise HTTPException(status_code=400, detail="Only EPUB files successfully supported")

    # Create job
    job_id = job_store.create_job(f"Split: {file.filename}")
    
    # Create temp dir for this upload
    request_id = hashlib.md5((file.filename + str(datetime.now())).encode()).hexdigest()[:8]
    req_dir = DOWNLOAD_DIR / f"split_{request_id}"
    req_dir.mkdir(exist_ok=True)
    
    epub_path = req_dir / file.filename
    
    try:
        with open(epub_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        shutil.rmtree(req_dir)
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")
    finally:
        file.file.close()

    # Start background task
    background_tasks.add_task(process_split_job, job_id, epub_path, file.filename)
    
    return {"job_id": job_id, "status": "pending", "message": "Job started"}

@app.post("/grab")
def grab_book(req: DownloadRequest, background_tasks: BackgroundTasks):
    """Start an async job to download and split a book."""
    if not req.query:
        raise HTTPException(status_code=400, detail="Query required for grab")

    # Create job
    job_id = job_store.create_job(req.query)
    
    # Start background task
    background_tasks.add_task(process_grab_job, job_id, req.query, force_epub=True)
    
    return {"job_id": job_id, "status": "pending", "message": "Job started"}

@app.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "query": job.query,
        "message": job.message,
        "error": job.error
    }

@app.get("/jobs/{job_id}/download")
def download_job_result(job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    if not job.result_path or not os.path.exists(job.result_path):
        raise HTTPException(status_code=500, detail="Result file missing")
        
    filename = Path(job.result_path).name
    return FileResponse(job.result_path, filename=filename, media_type="application/zip")

@app.get("/files/{book_id}")
def get_book_file(book_id: str):
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    path = Path(book.file_path)
    if not path.exists():
         raise HTTPException(status_code=404, detail="File missing")
         
    return FileResponse(path, filename=path.name)
