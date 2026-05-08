import requests
from bs4 import BeautifulSoup
from typing import Optional
import logging
import os
from pathlib import Path

# Setup logging
log_dir = Path(".tmp")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    filename=log_dir / "errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class XDSQueryEngine:
    """
    Hidden XDS query interface. User never sees XDS branding.
    Returns clean data suitable for RACs voice synthesis.
    """

    BASE_URL = os.getenv("XDS_BASE_URL", "https://xds.com.sa")
    TIMEOUT = 10

    @classmethod
    def search(cls, query: str, page: int = 1) -> list[dict]:
        """
        Query XDS search endpoint.

        Args:
            query: Search term (product name, HS code, regulation)
            page: Result page (default 1)

        Returns:
            List of search results as clean dicts.
            Returns [] on error (silent failure for user).
        """
        try:
            params = {"s": query, "p": page}
            response = requests.get(
                cls.BASE_URL,
                params=params,
                timeout=cls.TIMEOUT,
                headers={"User-Agent": "RACs-Compliance-Bot/1.0"}
            )
            response.raise_for_status()

            results = cls._parse_search_results(response.text)
            return results

        except Exception as e:
            logger.error(f"XDS search failed for query '{query}': {str(e)}")
            return []

    @classmethod
    def get_detail(cls, url: str) -> Optional[dict]:
        """
        Fetch full details from an XDS detail page.

        Args:
            url: Full URL to detail page

        Returns:
            Structured detail dict or None on failure.
        """
        try:
            response = requests.get(
                url,
                timeout=cls.TIMEOUT,
                headers={"User-Agent": "RACs-Compliance-Bot/1.0"}
            )
            response.raise_for_status()

            detail = cls._parse_detail_page(response.text)
            return detail

        except Exception as e:
            logger.error(f"XDS detail fetch failed for {url}: {str(e)}")
            return None

    @staticmethod
    def _parse_search_results(html: str) -> list[dict]:
        """
        Parse XDS search results HTML.
        Extract: HS code, product name, regulation, certification type, standards.
        Return clean dict (zero XDS branding in keys).
        """
        results = []

        try:
            soup = BeautifulSoup(html, "html.parser")

            # XDS uses <div class="result"> for each search result
            # Adjust selectors based on actual XDS HTML structure
            result_items = soup.find_all("div", class_="result")

            for item in result_items:
                try:
                    # Extract data from item
                    title_elem = item.find("h2", class_="title")
                    desc_elem = item.find("p", class_="description")
                    code_elem = item.find("span", class_="hs-code")
                    reg_elem = item.find("span", class_="regulation")
                    cert_elem = item.find("span", class_="certification-type")
                    detail_link = item.find("a", class_="detail-link")

                    result_dict = {
                        "product_name": title_elem.get_text(strip=True) if title_elem else "",
                        "description": desc_elem.get_text(strip=True) if desc_elem else "",
                        "hs_code": code_elem.get_text(strip=True) if code_elem else "",
                        "regulation": reg_elem.get_text(strip=True) if reg_elem else "",
                        "certification_type": cert_elem.get_text(strip=True) if cert_elem else "",
                        "detail_url": detail_link.get("href") if detail_link else ""
                    }

                    # Only add if we got at least a product name
                    if result_dict.get("product_name"):
                        results.append(result_dict)

                except Exception as e:
                    logger.error(f"Failed to parse individual result: {str(e)}")
                    continue

            return results

        except Exception as e:
            logger.error(f"Failed to parse search results HTML: {str(e)}")
            return []

    @staticmethod
    def _parse_detail_page(html: str) -> Optional[dict]:
        """
        Parse XDS detail page HTML.
        Extract: certification procedure, documents required, accredited bodies, standards.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Example parsing (adjust selectors to actual XDS structure)
            title_elem = soup.find("h1", class_="product-title")
            procedure_elem = soup.find("div", class_="certification-procedure")
            docs_elem = soup.find("div", class_="required-documents")
            standards_elem = soup.find("div", class_="applicable-standards")
            bodies_elem = soup.find("div", class_="accredited-bodies")

            detail_dict = {
                "product_name": title_elem.get_text(strip=True) if title_elem else "",
                "certification_procedure": procedure_elem.get_text(strip=True) if procedure_elem else "",
                "required_documents": docs_elem.get_text(strip=True) if docs_elem else "",
                "applicable_standards": standards_elem.get_text(strip=True) if standards_elem else "",
                "accredited_bodies": bodies_elem.get_text(strip=True) if bodies_elem else ""
            }

            return detail_dict if detail_dict.get("product_name") else None

        except Exception as e:
            logger.error(f"Failed to parse detail page: {str(e)}")
            return None


if __name__ == "__main__":
    # Quick test
    print("Testing XDS query engine...")
    results = XDSQueryEngine.search("electric scooter")
    print(f"Found {len(results)} results")
    if results:
        print(f"First result: {results[0]}")
