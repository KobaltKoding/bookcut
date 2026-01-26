"""Browser-based download using Playwright for automated WebView-like access."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console

console = Console()


class BrowserDownloader:
    """Downloads books using a headless browser to bypass anti-bot protection."""

    BASE_URL = "https://annas-archive.li"

    def __init__(self, download_dir: Path) -> None:
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def download(
        self,
        md5: str,
        format: str,
        on_status: callable = None,
        headless: bool = True,
    ) -> Path | None:
        """
        Download a book using headless browser.

        Args:
            md5: Book MD5 hash
            format: File format (epub, pdf, etc.)
            on_status: Callback for status updates

        Returns:
            Path to downloaded file or None if failed
        """
        def status(msg: str) -> None:
            if on_status:
                on_status(msg)
            else:
                console.print(f"[dim]{msg}[/dim]")

        target_file = self.download_dir / f"{md5}.{format}"

        with sync_playwright() as p:
            if headless:
                status("Launching headless browser...")
            else:
                status("Launching browser (complete any CAPTCHA in the window)...")

            browser = p.chromium.launch(
                headless=headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                accept_downloads=True,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            # Set download path
            page = context.new_page()

            try:
                # Go directly to slow_download page (skip book page)
                slow_download_url = f"{self.BASE_URL}/slow_download/{md5}/0/0"
                status(f"Navigating to download page...")
                page.goto(slow_download_url, wait_until="domcontentloaded", timeout=30000)

                # Wait for page to fully load
                time.sleep(2)

                # Check for DDoS-Guard protection page
                if "DDoS-Guard" in page.title() or "ddos" in page.content().lower():
                    if headless:
                        status("DDoS protection detected - use --visible flag to solve manually")
                        return None
                    else:
                        status("Waiting for you to complete DDoS-Guard check...")
                        # Wait up to 2 minutes for user to solve CAPTCHA
                        for _ in range(120):
                            time.sleep(1)
                            if "DDoS-Guard" not in page.title():
                                status("Protection bypassed!")
                                break
                        else:
                            status("Timeout waiting for DDoS-Guard")
                            return None

                # Check if we need to wait for a countdown
                countdown = page.locator('text=/\\d+ seconds?/i').first
                try:
                    if countdown.is_visible(timeout=2000):
                        status("Waiting for countdown timer...")
                        # Wait up to 60 seconds for countdown
                        for _ in range(60):
                            time.sleep(1)
                            try:
                                if not countdown.is_visible(timeout=1000):
                                    break
                            except:
                                break
                except:
                    pass  # No countdown found

                # Look for download links on the slow_download page
                # These are typically IPFS or direct links
                download_selectors = [
                    'a[href*="ipfs.io"]',
                    'a[href*="dweb.link"]',
                    'a[href*="cloudflare-ipfs"]',
                    'a[href*="pinata"]',
                    'a:has-text("Download")',
                    'a:has-text("GET")',
                    'a[href*="/get/"]',
                    'a[href*="download"]',
                ]

                downloaded_path = None

                for selector in download_selectors:
                    links = page.locator(selector).all()
                    if links:
                        status(f"Found {len(links)} download link(s), trying...")

                        for link in links[:3]:  # Try first 3 links
                            try:
                                href = link.get_attribute('href')
                                if not href or 'javascript:' in href:
                                    continue

                                status(f"Trying: {href[:60]}...")

                                # Start download
                                with page.expect_download(timeout=90000) as download_info:
                                    link.click()

                                download = download_info.value
                                status(f"Downloading: {download.suggested_filename}")

                                # Wait for download and save
                                temp_path = download.path()
                                if temp_path and Path(temp_path).exists():
                                    shutil.copy(temp_path, target_file)
                                    downloaded_path = target_file
                                    status(f"Saved to: {target_file}")
                                    break

                            except PlaywrightTimeout:
                                status("Link timed out, trying next...")
                                continue
                            except Exception as e:
                                status(f"Link failed: {e}")
                                continue

                        if downloaded_path:
                            break

                return downloaded_path

            except PlaywrightTimeout as e:
                status(f"Timeout: {e}")
                return None
            except Exception as e:
                status(f"Error: {e}")
                return None
            finally:
                browser.close()

    def download_with_retry(
        self,
        md5: str,
        format: str,
        max_retries: int = 2,
        on_status: callable = None,
        headless: bool = True,
    ) -> Path | None:
        """Download with retry logic."""
        for attempt in range(max_retries):
            if attempt > 0:
                if on_status:
                    on_status(f"Retry attempt {attempt + 1}/{max_retries}...")

            result = self.download(md5, format, on_status, headless=headless)
            if result:
                return result

        return None
