"""
Direct LLM-based extraction without CSS selector inference.

This is a simplified alternative to webdriver_extractor.py that:
1. Loads the page with Selenium
2. Converts HTML to markdown
3. Sends directly to Claude for extraction
4. Returns structured data

No selector inference, no caching, just pure LLM extraction.
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException
import html2text
import time
import os
import shutil


class DirectExtractor:
    """Simplified extractor using direct LLM extraction."""

    def __init__(self, url=None, selectors=None):
        """
        Initialize the extractor with a headless Chrome browser.

        Args:
            url: URL to scrape (optional, can be set later via navigate())
            selectors: CSS selectors (unused in direct extraction, kept for compatibility)
        """
        # Clean up old Chrome data from previous Lambda invocations
        for dir_path in ['/tmp/chrome-user-data', '/tmp/chrome-data', '/tmp/chrome-cache', '/tmp/cache']:
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path, ignore_errors=True)

        # Force all cache/temp operations to use /tmp (only writable dir in Lambda)
        os.environ['HOME'] = '/tmp'
        os.environ['TMPDIR'] = '/tmp'
        os.environ['TEMP'] = '/tmp'
        os.environ['TMP'] = '/tmp'

        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--single-process')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-dev-tools')
        chrome_options.add_argument('--no-zygote')

        # Additional stability options for Lambda
        chrome_options.add_argument('--disable-setuid-sandbox')
        chrome_options.add_argument('--disable-logging')
        chrome_options.add_argument('--log-level=3')
        chrome_options.add_argument('--disable-background-networking')
        chrome_options.add_argument('--disable-default-apps')
        chrome_options.add_argument('--disable-sync')
        chrome_options.add_argument('--metrics-recording-only')
        chrome_options.add_argument('--mute-audio')
        chrome_options.add_argument('--no-first-run')
        chrome_options.add_argument('--safebrowsing-disable-auto-update')
        chrome_options.add_argument('--disable-features=VizDisplayCompositor')

        # Prevent automation detection (can cause crashes on some sites)
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')

        # Additional Lambda stability
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--window-size=1920,1080')

        # Use /tmp for all Chrome data (only writable directory in Lambda)
        chrome_options.add_argument('--user-data-dir=/tmp/chrome-user-data')
        chrome_options.add_argument('--data-path=/tmp/chrome-data')
        chrome_options.add_argument('--disk-cache-dir=/tmp/chrome-cache')
        chrome_options.add_argument('--homedir=/tmp')

        # Set cache path for Selenium
        chrome_options.add_argument('--cache-dir=/tmp/cache')

        # Set binary location explicitly (Chrome installed via RPM in Dockerfile)
        chrome_options.binary_location = '/usr/bin/google-chrome'

        # Configure WebDriver Service with explicit paths
        service = Service(
            executable_path='/usr/local/bin/chromedriver',
            log_path='/tmp/chromedriver.log'
        )

        self.driver = webdriver.Chrome(service=service, options=chrome_options)

        # Set page load timeout (30 seconds)
        self.driver.set_page_load_timeout(30)

        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.url = url
        self.selectors = selectors

    def navigate(self, url, max_retries=2):
        """
        Navigate to a URL with retry logic.

        Args:
            url: The URL to navigate to
            max_retries: Number of times to retry on failure (default: 2)

        Raises:
            WebDriverException: If all retries fail
        """
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                self.driver.get(url)
                # Wait a moment for page to stabilize
                time.sleep(2)
                return
            except (TimeoutException, WebDriverException) as e:
                last_error = e
                if attempt < max_retries:
                    print(f"Navigation attempt {attempt + 1} failed, retrying...")
                    time.sleep(1)
                else:
                    print(f"All {max_retries + 1} navigation attempts failed")

        raise last_error

    def get_page_markdown(self):
        """
        Get the current page content as markdown.

        Returns:
            str: Page HTML converted to markdown
        """
        # Get the body HTML
        body_html = self.driver.execute_script("return document.body.innerHTML")

        # Convert to markdown
        markdown = self.html_converter.handle(body_html)

        return markdown

    def extract(self):
        """
        Extract page content as markdown (Lambda-compatible method).

        Navigates to self.url if set, then returns page markdown.

        Returns:
            str: Page HTML converted to markdown

        Raises:
            ValueError: If no URL was provided
        """
        if not self.url:
            raise ValueError("No URL provided to extract(). Set url in constructor or call navigate() first.")

        self.navigate(self.url)
        return self.get_page_markdown()

    def close(self):
        """Close the browser."""
        try:
            self.driver.quit()
        except:
            pass

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
