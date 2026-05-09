import requests
from bs4 import BeautifulSoup
from typing import Optional
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

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
            # Disable SSL verification for Windows certificate issues
            response = requests.get(
                cls.BASE_URL,
                params=params,
                timeout=cls.TIMEOUT,
                headers={"User-Agent": "RACs-Compliance-Bot/1.0"},
                verify=False
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
                headers={"User-Agent": "RACs-Compliance-Bot/1.0"},
                verify=False
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
        Parse XDS search results from HTML table.
        Table structure: TD0=HS Code, TD1=Product, TD2=Regulation, TD3=View button.
        Extract ONLY what XDS provides—no hallucinated data.
        """
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table")

            if not table:
                return []

            rows = table.find_all("tr")[1:]  # Skip header row

            for row in rows:
                try:
                    tds = row.find_all("td")
                    if len(tds) < 4:
                        continue

                    # TD0: HS Code link
                    hs_code_link = tds[0].find("a")
                    hs_code = hs_code_link.get_text(strip=True) if hs_code_link else None
                    if not hs_code:
                        continue

                    # TD1: Product Description
                    # First div = product name; skip parent category divs
                    description_divs = tds[1].find_all("div")
                    product_name = description_divs[0].get_text(strip=True) if description_divs else None
                    parent_category = description_divs[1].get_text(strip=True) if len(description_divs) > 1 else None

                    # TD2: Regulation Info
                    # Div 0 = regulation name; div 3 = certification type (divs 1-2 are spacing/empty)
                    regulation_divs = tds[2].find_all("div")
                    regulation_name = regulation_divs[0].get_text(strip=True) if regulation_divs else None
                    certification_type = regulation_divs[3].get_text(strip=True) if len(regulation_divs) > 3 else None

                    # TD3: Detail link (View button)
                    detail_link = tds[3].find("a")
                    detail_url = detail_link.get("href") if detail_link else None

                    # Make detail URL absolute if needed
                    if detail_url and not detail_url.startswith("http"):
                        base = os.getenv("XDS_BASE_URL", "https://xds-solutions.com").rsplit("/", 1)[0]
                        detail_url = base + detail_url

                    if hs_code and product_name:
                        result_dict = {
                            "hs_code": hs_code,
                            "product_name": product_name,
                            "parent_category": parent_category,
                            "regulation": regulation_name,
                            "certification_type": certification_type,
                            "detail_url": detail_url
                        }
                        results.append(result_dict)

                except Exception as e:
                    logger.error(f"Failed to parse table row: {str(e)}")
                    continue

            return results

        except Exception as e:
            logger.error(f"Failed to parse search results: {str(e)}")
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
