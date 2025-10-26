"""
URL validators and builders for Congress.gov links
"""
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_congress_url(url: str, timeout: int = 5) -> bool:
    """Check if URL returns HTTP 200"""
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"URL validation failed for {url}: {e}")
        return False


def build_member_url(bioguide_id: str, name: str = "") -> str:
    """Construct Congress.gov member URL"""
    if not bioguide_id:
        return ""
    
    # Format: https://www.congress.gov/member/{bioguide_id}
    # Or with name: https://www.congress.gov/member/first-last/{bioguide_id}
    
    if name:
        # Clean and format name for URL
        name_slug = name.lower().replace(' ', '-').replace('.', '')
        # Remove titles like "Rep." "Sen." etc
        name_slug = name_slug.replace('rep-', '').replace('sen-', '').replace('mr-', '').replace('ms-', '').replace('mrs-', '')
        return f"https://www.congress.gov/member/{name_slug}/{bioguide_id}"
    else:
        return f"https://www.congress.gov/member/{bioguide_id}"


def build_committee_url(system_code: str, name: str = "") -> str:
    """Construct Congress.gov committee URL"""
    if not system_code:
        return ""
    
    # Format: https://www.congress.gov/committee/{system_code}
    # Example: https://www.congress.gov/committee/house-energy-and-commerce/hsif00
    
    if name:
        # Create slug from name
        name_slug = name.lower().replace(' ', '-').replace(',', '').replace('--', '-')
        # Remove common words
        name_slug = name_slug.replace('committee-on-', '').replace('the-', '')
        return f"https://www.congress.gov/committee/{name_slug}/{system_code.lower()}"
    else:
        return f"https://www.congress.gov/committee/{system_code.lower()}"


def build_bill_url(congress: int, bill_type: str, number: int) -> str:
    """Construct Congress.gov bill URL"""
    # Format: https://www.congress.gov/bill/118th-congress/house-bill/1
    
    # Map bill type codes to URL format
    type_map = {
        'hr': 'house-bill',
        'hres': 'house-resolution',
        'hjres': 'house-joint-resolution',
        'hconres': 'house-concurrent-resolution',
        's': 'senate-bill',
        'sres': 'senate-resolution',
        'sjres': 'senate-joint-resolution',
        'sconres': 'senate-concurrent-resolution'
    }
    
    bill_type_lower = bill_type.lower()
    bill_type_url = type_map.get(bill_type_lower, bill_type_lower)
    
    return f"https://www.congress.gov/bill/{congress}th-congress/{bill_type_url}/{number}"


def build_amendment_url(congress: int, amendment_type: str, number: int) -> str:
    """Construct Congress.gov amendment URL"""
    # Format: https://www.congress.gov/amendment/118th-congress/house-amendment/1
    
    type_map = {
        'hamdt': 'house-amendment',
        'samdt': 'senate-amendment',
        'suamdt': 'senate-amendment'
    }
    
    amdt_type = type_map.get(amendment_type.lower(), 'amendment')
    
    return f"https://www.congress.gov/amendment/{congress}th-congress/{amdt_type}/{number}"


def normalize_bill_id_for_url(bill_id: str) -> dict:
    """
    Parse bill ID into components for URL building
    
    Examples:
        H.R.1 -> {type: 'house-bill', number: 1}
        S.2296 -> {type: 'senate-bill', number: 2296}
        H.Res.353 -> {type: 'house-resolution', number: 353}
    """
    result = {
        'type': '',
        'type_code': '',
        'number': 0,
        'formatted': ''
    }
    
    # Type mapping
    type_map = {
        'H.R.': {'code': 'hr', 'url': 'house-bill'},
        'S.': {'code': 's', 'url': 'senate-bill'},
        'H.Res.': {'code': 'hres', 'url': 'house-resolution'},
        'S.Res.': {'code': 'sres', 'url': 'senate-resolution'},
        'H.J.Res.': {'code': 'hjres', 'url': 'house-joint-resolution'},
        'S.J.Res.': {'code': 'sjres', 'url': 'senate-joint-resolution'},
        'H.Con.Res.': {'code': 'hconres', 'url': 'house-concurrent-resolution'},
        'S.Con.Res.': {'code': 'sconres', 'url': 'senate-concurrent-resolution'},
    }
    
    for prefix, mapping in type_map.items():
        if bill_id.startswith(prefix):
            number_str = bill_id.replace(prefix, '').strip()
            try:
                result['number'] = int(number_str)
                result['type'] = mapping['url']
                result['type_code'] = mapping['code']
                result['formatted'] = f"{mapping['code']}{number_str}"
                break
            except ValueError:
                logger.error(f"Could not parse bill number from {bill_id}")
    
    return result


def extract_bioguide_from_url(url: str) -> Optional[str]:
    """Extract bioguide ID from Congress.gov member URL"""
    # URL format: https://www.congress.gov/member/john-doe/P000197
    parts = url.rstrip('/').split('/')
    if len(parts) > 0:
        return parts[-1]
    return None


def extract_system_code_from_url(url: str) -> Optional[str]:
    """Extract system code from Congress.gov committee URL"""
    # URL format: https://www.congress.gov/committee/house-energy/hsif00
    parts = url.rstrip('/').split('/')
    if len(parts) > 0:
        return parts[-1]
    return None
