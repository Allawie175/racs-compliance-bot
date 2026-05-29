import os
import requests
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class LeadCapture:
    """
    Airtable lead capture integration.
    Pushes qualified leads to RACS CRM for follow-up.
    """

    AIRTABLE_BASE_URL = "https://api.airtable.com/v0"

    def __init__(self):
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        self.base_id = os.getenv("AIRTABLE_BASE_ID")
        self.table_name = os.getenv("AIRTABLE_TABLE_NAME")

        if not all([self.api_key, self.base_id, self.table_name]):
            logger.warning("Airtable configuration incomplete. Lead capture disabled.")
            self.enabled = False
        else:
            self.enabled = True

    def submit_lead(self, lead_data: dict) -> bool:
        """
        Submit a lead to Airtable.

        Args:
            lead_data: Dict with keys: name, email, phone, product_interest, chat_id

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.warning("Airtable not configured. Skipping lead submission.")
            return False

        try:
            url = f"{self.AIRTABLE_BASE_URL}/{self.base_id}/{self.table_name}"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "records": [
                    {
                        "fields": {
                            "Name": lead_data.get("name", ""),
                            "Email": lead_data.get("email", ""),
                            "Phone": lead_data.get("phone", ""),
                            "Product Interest": lead_data.get("product_interest", ""),
                            "Chat ID": lead_data.get("chat_id", ""),
                            "Source": "Telegram Bot",
                            "Captured At": datetime.now().isoformat()
                        }
                    }
                ]
            }

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=10
            )

            if response.status_code in [200, 201]:
                print(f"[LeadCapture] Lead submitted successfully: {lead_data.get('email')}")
                return True
            else:
                print(f"[LeadCapture] Airtable submission failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"[LeadCapture] Error submitting lead to Airtable: {type(e).__name__}: {e}")
            return False

    def get_lead_status(self, email: str) -> Optional[dict]:
        """
        Check if a lead already exists (optional, for duplicate detection).
        """
        if not self.enabled:
            return None

        try:
            url = f"{self.AIRTABLE_BASE_URL}/{self.base_id}/{self.table_name}"
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }

            # Filter by email
            params = {
                "filterByFormula": f"{{Email}} = '{email}'"
            }

            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                records = response.json().get("records", [])
                return records[0] if records else None
            else:
                logger.warning(f"Failed to check lead status: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error checking lead status: {str(e)}")
            return None


if __name__ == "__main__":
    # Test lead capture
    lc = LeadCapture()
    if lc.enabled:
        test_lead = {
            "name": "Test User",
            "email": "test@example.com",
            "phone": "+966-XX-XXXX-XXXX",
            "product_interest": "Electric Vehicles",
            "chat_id": "test_123"
        }
        result = lc.submit_lead(test_lead)
        print(f"Lead submission: {'Success' if result else 'Failed'}")
    else:
        print("Airtable not configured.")
