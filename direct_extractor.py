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
import html2text


class DirectExtractor:
    """Simplified extractor using direct LLM extraction."""

    def __init__(self):
        """Initialize the extractor with a headless Chrome browser."""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')

        self.driver = webdriver.Chrome(options=chrome_options)
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True

    def navigate(self, url):
        """
        Navigate to a URL.

        Args:
            url: The URL to navigate to
        """
        self.driver.get(url)

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
