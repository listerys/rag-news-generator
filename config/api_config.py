"""
Congress.gov API Configuration
"""
import os

# API Configuration
CONGRESS_API_BASE_URL = "https://api.congress.gov/v3"
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY", "")

# Rate Limiting
API_RATE_LIMIT_DELAY = 0.1  # Seconds between requests
API_MAX_RETRIES = 3
API_RETRY_DELAY = 2  # Seconds
API_TIMEOUT = 30  # Seconds

# Pagination
API_DEFAULT_LIMIT = 250
API_MAX_LIMIT = 250

# Cache Configuration
ENABLE_API_CACHE = True
CACHE_TTL = 3600  # 1 hour in seconds

# Endpoints
ENDPOINTS = {
    'bills': '/bill/{congress}/{billType}/{billNumber}',
    'bill_actions': '/bill/{congress}/{billType}/{billNumber}/actions',
    'bill_amendments': '/bill/{congress}/{billType}/{billNumber}/amendments',
    'bill_committees': '/bill/{congress}/{billType}/{billNumber}/committees',
    'bill_cosponsors': '/bill/{congress}/{billType}/{billNumber}/cosponsors',
    'bill_related': '/bill/{congress}/{billType}/{billNumber}/relatedbills',
    'bill_subjects': '/bill/{congress}/{billType}/{billNumber}/subjects',
    'bill_summaries': '/bill/{congress}/{billType}/{billNumber}/summaries',
    'bill_text': '/bill/{congress}/{billType}/{billNumber}/text',
    'bill_titles': '/bill/{congress}/{billType}/{billNumber}/titles',
    'member': '/member/{bioguideId}',
    'congress_current': '/congress/current',
}

# Bill Type Mapping
BILL_TYPE_MAP = {
    'H.R.': 'hr',
    'S.': 's',
    'H.Res.': 'hres',
    'S.Res.': 'sres',
    'H.J.Res.': 'hjres',
    'S.J.Res.': 'sjres',
    'H.Con.Res.': 'hconres',
    'S.Con.Res.': 'sconres',
}

# Reverse mapping
BILL_CODE_TO_NAME = {
    'hr': 'House Bill',
    's': 'Senate Bill',
    'hres': 'House Resolution',
    'sres': 'Senate Resolution',
    'hjres': 'House Joint Resolution',
    'sjres': 'Senate Joint Resolution',
    'hconres': 'House Concurrent Resolution',
    'sconres': 'Senate Concurrent Resolution',
}
