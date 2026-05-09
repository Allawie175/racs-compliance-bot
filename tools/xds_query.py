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
                        # href already includes full path from root (/certification/saudi-arabia/...)
                        # so just prepend the domain
                        detail_url = "https://xds-solutions.com" + detail_url

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
        Parse XDS detail page to extract regulation background, products covered, and requirements.
        Returns structured data for Claude to synthesize into response.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            all_text = soup.get_text(separator="\n", strip=True)

            detail_dict = {}

            # Extract regulation background (description before Products Covered)
            if "The Technical Regulation for" in all_text or "Technical Regulation for" in all_text:
                # Find text between "Technical Regulation for" and "Products Covered"
                start = all_text.find("Technical Regulation for")
                if start != -1:
                    end = all_text.find("Products Covered", start)
                    if end == -1:
                        end = all_text.find("Certification Requirements", start)

                    if end != -1:
                        regulation_text = all_text[start:end].strip()
                        # Clean up and truncate to reasonable length
                        regulation_text = regulation_text.replace("\n", " ")[:300]
                        detail_dict["regulation_description"] = regulation_text

            # Extract products covered section
            if "Products Covered" in all_text:
                start = all_text.find("Products Covered")
                # Find end (either at Certification Requirements or next section)
                end = all_text.find("Certification Requirements", start)
                if end == -1:
                    end = all_text.find("Product Classification", start)
                if end == -1:
                    end = start + 500  # Just take next 500 chars

                products_section = all_text[start:end].strip()
                detail_dict["products_covered"] = products_section[:400]

            # Extract certification requirements with descriptions
            if "Test Report:" in all_text:
                start = all_text.find("Test Report:")
                end = all_text.find("Product Photos:", start)
                if end == -1:
                    end = start + 200
                test_req = all_text[start:end].replace("\n", " ").strip()[:150]
                detail_dict["test_report_requirement"] = test_req

            if "Product Photos:" in all_text:
                start = all_text.find("Product Photos:")
                end = all_text.find("Data Sheet", start)
                if end == -1:
                    end = start + 200
                photos_req = all_text[start:end].replace("\n", " ").strip()[:150]
                detail_dict["photos_requirement"] = photos_req

            if "Data Sheet" in all_text:
                start = all_text.find("Data Sheet")
                end = all_text.find("Product Classification", start)
                if end == -1:
                    end = start + 200
                data_req = all_text[start:end].replace("\n", " ").strip()[:150]
                detail_dict["data_sheets_requirement"] = data_req

            # Extract product classification details
            if "Type 1a Assessment" in all_text:
                start = all_text.find("Type 1a Assessment")
                end = all_text.find("Note:", start)
                if end == -1:
                    end = start + 200
                classification = all_text[start:end].replace("\n", " ").strip()[:200]
                detail_dict["product_classification"] = classification

            # Extract additional certificates note
            if "G-Mark Certificate" in all_text or "IECEE" in all_text:
                start = all_text.find("Note:")
                if start != -1:
                    end = all_text.find("Please note", start)
                    if end == -1:
                        end = start + 300
                    note = all_text[start:end].replace("\n", " ").strip()[:250]
                    detail_dict["additional_certificates_note"] = note

            return detail_dict if detail_dict else None

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
