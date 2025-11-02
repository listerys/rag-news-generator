import os
import requests
import time
from typing import Dict, List, Optional
import logging
import json

import redis

logger = logging.getLogger(__name__)

class CongressAPIClient:
    BASE_URL = "https://api.congress.gov/v3"
    
    def __init__(self):
        self.api_key = os.getenv("CONGRESS_API_KEY")
        self.session = requests.Session()
        self.cache = {}
        # Redis cache (shared across workers)
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            self.redis = redis.from_url(redis_url, decode_responses=True)
            # Smoke test connection
            self.redis.ping()
            self._redis_ok = True
        except Exception:
            self.redis = None
            self._redis_ok = False
        self.ttl_seconds = int(os.getenv("CONGRESS_API_CACHE_TTL", "86400"))  # 1 day
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make API request with caching (Redis + local) and gentle backoff."""
        if params is None:
            params = {}
        # Build cache key
        cache_key = f"cg:{endpoint}:{json.dumps(params, sort_keys=True)}"

        # Check Redis cache
        if self._redis_ok:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass

        # Check local cache
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Prepare request
        params['api_key'] = self.api_key
        params['format'] = 'json'
        url = f"{self.BASE_URL}/{endpoint}"

        backoff = 0.25
        max_backoff = 4.0
        for attempt in range(6):
            try:
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise requests.RequestException(f"HTTP {response.status_code}")
                response.raise_for_status()
                data = response.json()

                # Store caches
                self.cache[cache_key] = data
                if self._redis_ok:
                    try:
                        self.redis.setex(cache_key, self.ttl_seconds, json.dumps(data))
                    except Exception:
                        pass

                # Gentle pacing
                time.sleep(0.05)
                return data
            except requests.RequestException as e:
                if attempt == 5:
                    logger.error(f"API request failed: {url} - {e}")
                    return {}
                time.sleep(backoff)
                backoff = min(max_backoff, backoff * 2)

    def _parse_bill_id(self, bill_id: str) -> tuple:
        """
        Parse bill_id into (congress, bill_type, bill_number)
        Handles both normalized (sres412-119) and original (S.Res.412) formats
        """
        parts = bill_id.split('-')
        if len(parts) > 1:
            # Normalized format: sres412-119
            congress = parts[1]
            bill_part = parts[0]
            bill_type = ''.join([c for c in bill_part if not c.isdigit()]).lower()
            bill_number = ''.join([c for c in bill_part if c.isdigit()])
        else:
            # Original format: S.Res.412 - normalize it
            logger.warning(f"Received non-normalized bill_id: {bill_id}, normalizing...")
            congress = "118"  # Default to current congress
            # Handle different bill formats
            bill_type_map = {
                'H.R.': 'hr',
                'S.': 's',
                'H.Res.': 'hres',
                'S.Res.': 'sres',
                'H.J.Res.': 'hjres',
                'S.J.Res.': 'sjres',
                'H.Con.Res.': 'hconres',
                'S.Con.Res.': 'sconres'
            }
            bill_type = None
            bill_number = None
            for prefix, code in bill_type_map.items():
                if bill_id.startswith(prefix):
                    bill_type = code
                    bill_number = bill_id.replace(prefix, '').strip()
                    break

            if not bill_type or not bill_number:
                logger.error(f"Could not parse bill_id: {bill_id}")
                return None, None, None

        # Ensure bill_type is lowercase and clean
        bill_type = bill_type.lower().replace('.', '')
        return congress, bill_type, bill_number

    def get_bill_details(self, bill_id: str) -> Dict:
        """Fetch bill details with special handling for problematic bills"""
        # Parse bill_id using helper method
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}"
        result = self._make_request(endpoint)
        
        # Additional validation for resolutions
        if bill_type in ['sres', 'hres']:
            if not result or 'bill' not in result:
                logger.warning(f"No bill data returned for {bill_id} from {endpoint}")
            elif 'bill' in result:
                bill_data = result['bill']
                if not bill_data.get('title'):
                    logger.warning(f"No title in bill data for {bill_id}")
                if not bill_data.get('sponsors'):
                    logger.warning(f"No sponsors in bill data for {bill_id}")
        
        return result
    
    def get_bill_actions(self, bill_id: str) -> Dict:
        """Fetch bill actions/status"""
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}/actions"
        return self._make_request(endpoint)
    
    def get_bill_committees(self, bill_id: str) -> Dict:
        """Fetch committees"""
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}/committees"
        return self._make_request(endpoint)
    
    def get_bill_cosponsors(self, bill_id: str) -> Dict:
        """Fetch ALL cosponsors with pagination support"""
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}/cosponsors"
        
        # Fetch first page
        first_page = self._make_request(endpoint, params={'limit': 250, 'offset': 0})
        
        if not first_page or 'cosponsors' not in first_page:
            return first_page
        
        all_cosponsors = first_page.get('cosponsors', [])
        pagination = first_page.get('pagination', {})
        total_count = pagination.get('count', len(all_cosponsors))
        
        # Fetch remaining pages if needed
        offset = 250
        while offset < total_count and offset < 500:  # Cap at 500 cosponsors
            next_page = self._make_request(endpoint, params={'limit': 250, 'offset': offset})
            if next_page and 'cosponsors' in next_page:
                all_cosponsors.extend(next_page['cosponsors'])
                offset += 250
            else:
                break
        
        # Return combined result
        result = first_page.copy()
        result['cosponsors'] = all_cosponsors
        result['pagination'] = {'count': len(all_cosponsors), 'total_actual': total_count}
        
        logger.info(f"Fetched {len(all_cosponsors)} cosponsors for {bill_id}")
        return result
    
    def get_bill_amendments(self, bill_id: str) -> Dict:
        """Fetch ALL amendments with pagination support"""
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}/amendments"
        
        # Fetch first page to get total count
        first_page = self._make_request(endpoint, params={'limit': 250, 'offset': 0})
        
        if not first_page or 'amendments' not in first_page:
            return first_page
        
        all_amendments = first_page.get('amendments', [])
        pagination = first_page.get('pagination', {})
        total_count = pagination.get('count', len(all_amendments))
        
        # If more amendments exist, fetch remaining pages
        offset = 250
        while offset < total_count and offset < 1000:  # Cap at 1000 to avoid excessive API calls
            next_page = self._make_request(endpoint, params={'limit': 250, 'offset': offset})
            if next_page and 'amendments' in next_page:
                all_amendments.extend(next_page['amendments'])
                offset += 250
            else:
                break
        
        # Return combined result
        result = first_page.copy()
        result['amendments'] = all_amendments
        result['pagination'] = {'count': len(all_amendments), 'total_actual': total_count}
        
        logger.info(f"Fetched {len(all_amendments)} amendments for {bill_id}")
        return result
    
    def get_member_details(self, bioguide_id: str) -> Dict:
        """Fetch member details"""
        endpoint = f"member/{bioguide_id}"
        return self._make_request(endpoint)
    
    def get_current_congress(self) -> int:
        """Auto-detect the current Congress session"""
        try:
            endpoint = "congress/current"
            data = self._make_request(endpoint)
            
            if 'congress' in data:
                congress_number = data['congress'].get('number')
                if congress_number:
                    logger.info(f"Current Congress: {congress_number}")
                    return int(congress_number)
            
            # Fallback calculation based on year
            import datetime
            current_year = datetime.datetime.now().year
            # Congress sessions start in odd years
            # 118th Congress: 2023-2024, 119th: 2025-2026, etc.
            congress = 118 + ((current_year - 2023) // 2)
            logger.info(f"Calculated Congress session: {congress}")
            return congress
            
        except Exception as e:
            logger.warning(f"Failed to get current congress: {e}, defaulting to 118")
            return 118
    
    def get_bill_text(self, bill_id: str) -> Dict:
        """Fetch full bill text/summary"""
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}/text"
        return self._make_request(endpoint)
    
    def get_bill_summaries(self, bill_id: str) -> Dict:
        """Fetch bill summaries (official summaries of what bill does)"""
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}/summaries"
        return self._make_request(endpoint)
    
    def get_committee_reports(self, bill_id: str) -> Dict:
        """Fetch committee reports for hearing findings"""
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)

        if not congress or not bill_type or not bill_number:
            logger.error(f"Could not parse bill_id: {bill_id}")
            return {}

        endpoint = f"bill/{congress}/{bill_type}/{bill_number}/committeeReports"
        return self._make_request(endpoint)
    
    def get_recorded_votes(self, bill_id: str) -> Dict:
        """Fetch detailed vote breakdowns"""
        # Recorded votes are embedded in actions
        # This is a convenience wrapper
        return self.get_bill_actions(bill_id)