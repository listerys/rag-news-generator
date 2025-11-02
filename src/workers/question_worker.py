import json
import logging
import asyncio
from time import perf_counter
from kafka import KafkaConsumer, KafkaProducer
from congress_api.client import CongressAPIClient
from congress_api.parsers import (
    parse_bill_status, parse_sponsor_info, parse_cosponsors,
    parse_committees, parse_amendments, parse_votes, parse_hearings,
    parse_committee_reports, extract_bill_metadata
)
from llm.summarizer import LLMSummarizer
from database.state_store import StateStore
from utils.validators import build_member_url, build_committee_url, build_bill_url, normalize_bill_id_for_url
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QuestionWorker:
    def __init__(self):
        self.consumer = KafkaConsumer(
            'question_tasks',
            bootstrap_servers='kafka:29092',
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='question_workers',
            auto_offset_reset='earliest',
            # Extended timeouts for long LLM processing (128+ seconds observed)
            session_timeout_ms=300000,        # 5 minutes - max time between heartbeats
            heartbeat_interval_ms=30000,      # 30 seconds - how often to send heartbeats
            max_poll_interval_ms=600000       # 10 minutes - max time between polls
        )
        
        self.producer = KafkaProducer(
            bootstrap_servers='kafka:29092',
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        self.api_client = CongressAPIClient()
        self.llm = LLMSummarizer()
        self.state_store = StateStore()
    
    def process_question(self, task):
        """Process a single question task"""
        bill_id = task['bill_id']
        normalized_bill = task['normalized_bill_id']
        question_id = task['question_id']
        question_text = task['question_text']
        
        logger.info(f"Processing {bill_id} - Q{question_id}")
        
        # Check if already completed
        if self.state_store.is_question_completed(bill_id, question_id):
            logger.info(f"Question already answered: {bill_id} Q{question_id}")
            return
        
        # Fetch relevant data (concurrently)
        t0 = perf_counter()
        data = self.fetch_data(normalized_bill, task['api_endpoints'])

        # Validate that we got some data
        if not data or (not data.get('_raw') and not any(k in data for k in ['bill_status', 'sponsor_info', 'committees_info', 'cosponsors_info', 'amendments_info', 'votes_info', 'hearings_info'])):
            logger.error(f"No data fetched for {bill_id} - Q{question_id}. API may have failed or bill may not exist.")
            # Save empty answer indicating data unavailable
            answer = "Information not available - unable to retrieve data from Congress.gov API."
            self.state_store.save_answer(bill_id, question_id, answer, [])
            self.state_store.mark_question_complete(bill_id, question_id)
            return

        # Save bill metadata (if this is the first question)
        if question_id == 1 and '_raw' in data:
            raw_data = data['_raw']
            if 'bill_details' in raw_data:
                # Fetch committees if not already present
                committees_data = raw_data.get('committees')
                if not committees_data:
                    try:
                        committees_data = self.api_client.get_bill_committees(normalized_bill)
                    except Exception as e:
                        logger.warning(f"Could not fetch committees for metadata: {e}")
                        committees_data = {}
                
                metadata = extract_bill_metadata(raw_data['bill_details'], committees_data)
                
                # Validate metadata before saving
                bill_title = metadata.get('bill_title', '')
                sponsor_bioguide = metadata.get('sponsor_bioguide_id', '')
                committee_ids = metadata.get('committee_ids', [])
                
                if not bill_title:
                    logger.warning(f"No title found for {bill_id}, will use bill_id as fallback")
                if not sponsor_bioguide:
                    logger.warning(f"No sponsor bioguide ID found for {bill_id}")
                if not committee_ids:
                    logger.info(f"No committees found for {bill_id} (may be normal for resolutions)")
                
                self.state_store.save_bill_metadata(
                    bill_id,
                    bill_title,
                    sponsor_bioguide,
                    committee_ids,
                    normalized_bill
                )
        
        # Generate answer using LLM
        answer = self.llm.answer_question(question_text, data)

        # Extract hyperlinks
        raw_links = self.extract_hyperlinks(data, bill_id)
        # Validate links asynchronously but KEEP ALL (don't filter by validation)
        hyperlinks = self._validate_links_non_blocking(raw_links)
        
        # Store answer
        self.state_store.save_answer(bill_id, question_id, answer, hyperlinks)
        
        # Mark complete
        self.state_store.mark_question_complete(bill_id, question_id)
        
        elapsed = (perf_counter() - t0) * 1000
        logger.info(f"Completed {bill_id} - Q{question_id} in {elapsed:.0f} ms")
    
    def fetch_data(self, bill_id, endpoints):
        """Fetch data from Congress API and parse it"""
        data = {}
        raw_data = {}

        # Plan concurrent fetches for required endpoints
        async def _fetch_all():
            async with httpx.AsyncClient(timeout=20.0) as client:
                # Note: CongressAPIClient uses requests sync; rely on caching and parallelize logical calls
                # We parallelize by scheduling sync calls in threads where helpful.
                loop = asyncio.get_running_loop()

                async def _call(func, *args):
                    return await loop.run_in_executor(None, func, *args)

                tasks = []
                for endpoint in endpoints:
                    if endpoint == "bill_details":
                        tasks.append(_call(self.api_client.get_bill_details, bill_id))
                    elif endpoint == "actions":
                        tasks.append(_call(self.api_client.get_bill_actions, bill_id))
                    elif endpoint == "committees":
                        tasks.append(_call(self.api_client.get_bill_committees, bill_id))
                    elif endpoint == "cosponsors":
                        tasks.append(_call(self.api_client.get_bill_cosponsors, bill_id))
                    elif endpoint == "amendments":
                        tasks.append(_call(self.api_client.get_bill_amendments, bill_id))
                    elif endpoint == "committee_reports":
                        tasks.append(_call(self.api_client.get_committee_reports, bill_id))
                    elif endpoint == "sponsors":
                        # Sponsors are in bill_details
                        tasks.append(_call(self.api_client.get_bill_details, bill_id))
                    elif endpoint in ["votes", "recorded_votes"]:
                        # Votes are in actions
                        tasks.append(_call(self.api_client.get_bill_actions, bill_id))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Map results back
                idx = 0
                for endpoint in endpoints:
                    res = results[idx]
                    idx += 1
                    if isinstance(res, Exception):
                        logger.warning(f"Failed to fetch {endpoint} for {bill_id}: {res}")
                        continue
                    if not res or (isinstance(res, dict) and not res):
                        logger.warning(f"Empty response for {endpoint} for {bill_id}")
                        continue
                    if endpoint == "bill_details":
                        raw_data['bill_details'] = res
                    elif endpoint == "actions":
                        raw_data['actions'] = res
                    elif endpoint == "committees":
                        raw_data['committees'] = res
                    elif endpoint == "cosponsors":
                        raw_data['cosponsors'] = res
                    elif endpoint == "amendments":
                        raw_data['amendments'] = res
                    elif endpoint == "committee_reports":
                        raw_data['committee_reports'] = res
                    elif endpoint == "sponsors":
                        raw_data['bill_details'] = res
                    elif endpoint in ["votes", "recorded_votes"]:
                        raw_data['actions'] = res

        # Run concurrent fetch
        try:
            asyncio.run(_fetch_all())
        except RuntimeError:
            # Already in event loop (e.g., in certain environments)
            loop = asyncio.get_event_loop()
            loop.run_until_complete(_fetch_all())

        # Derive structured fields with error handling
        # Always fetch summaries to get full bill description
        summaries_data = {}
        try:
            summaries_data = self.api_client.get_bill_summaries(bill_id)
        except Exception as e:
            logger.debug(f"Could not fetch summaries for {bill_id}: {e}")

        try:
            if 'bill_details' in raw_data and 'actions' in raw_data:
                data['bill_status'] = parse_bill_status(raw_data['bill_details'], raw_data['actions'], summaries_data)
        except Exception as e:
            logger.warning(f"Error parsing bill status for {bill_id}: {e}")

        try:
            if 'bill_details' in raw_data:
                data['sponsor_info'] = parse_sponsor_info(raw_data['bill_details'])
        except Exception as e:
            logger.warning(f"Error parsing sponsor info for {bill_id}: {e}")

        try:
            if 'committees' in raw_data:
                data['committees_info'] = parse_committees(raw_data['committees'])
        except Exception as e:
            logger.warning(f"Error parsing committees for {bill_id}: {e}")

        try:
            if 'cosponsors' in raw_data and 'committees' in raw_data:
                data['cosponsors_info'] = parse_cosponsors(raw_data['cosponsors'], raw_data['committees'])
        except Exception as e:
            logger.warning(f"Error parsing cosponsors for {bill_id}: {e}")

        try:
            if 'amendments' in raw_data:
                data['amendments_info'] = parse_amendments(raw_data['amendments'])
        except Exception as e:
            logger.warning(f"Error parsing amendments for {bill_id}: {e}")

        try:
            if 'actions' in raw_data:
                data['votes_info'] = parse_votes(raw_data['actions'])
                data['hearings_info'] = parse_hearings(raw_data['actions'])
        except Exception as e:
            logger.warning(f"Error parsing votes/hearings for {bill_id}: {e}")

        try:
            if 'committee_reports' in raw_data:
                data['committee_reports_info'] = parse_committee_reports(raw_data['committee_reports'])
        except Exception as e:
            logger.warning(f"Error parsing committee reports for {bill_id}: {e}")

        # Store raw data for reference
        data['_raw'] = raw_data

        return data
    
    def extract_hyperlinks(self, data, bill_id):
        """Extract relevant Congress.gov URLs using validators with search variants"""
        links = []
        
        # Parse bill ID for URL construction
        bill_info = normalize_bill_id_for_url(bill_id)
        
        # Use congress from normalized id when available; fallback to 118
        # normalized format: hr1-118 -> parse congress suffix if present in metadata later
        congress = 118
        try:
            parts = data.get('_raw', {}).get('bill_details', {}).get('bill', {}).get('congress', '')
            if isinstance(parts, str) and parts.isdigit():
                congress = int(parts)
        except Exception:
            pass
        if bill_info['number'] > 0:
            bill_url = build_bill_url(congress, bill_info['type_code'], bill_info['number'])
            links.append({
                "text": bill_id,
                "url": bill_url,
                "search_variants": [bill_id]  # Exact match only for bill IDs
            })
        
        # Sponsor links
        if 'sponsor_info' in data:
            sponsor = data['sponsor_info']
            bioguide = sponsor.get('bioguide_id')
            name = sponsor.get('name')
            party = sponsor.get('party', '')
            state = sponsor.get('state', '')
            district = sponsor.get('district', '')
            
            if bioguide and name:
                sponsor_url = build_member_url(bioguide, name)
                # Create full display name with party/state/district
                full_name = name
                if party and state:
                    if district:
                        full_name = f"{name} ({party}-{state}-{district})"
                    else:
                        full_name = f"{name} ({party}-{state})"
                
                # Generate search variants
                variants = [name, full_name]
                # Add title variants (Rep., Sen.)
                if 'Rep.' in name or 'Senator' in name or 'Sen.' in name:
                    variants.append(name)
                else:
                    # Infer title from chamber if available
                    chamber = sponsor.get('chamber', '')
                    if chamber:
                        title = 'Sen.' if chamber.lower() == 'senate' else 'Rep.'
                        name_only = name.replace('Rep.', '').replace('Sen.', '').replace('Senator', '').strip()
                        variants.append(f"{title} {name_only}")
                
                links.append({
                    "text": full_name,
                    "url": sponsor_url,
                    "search_variants": list(set(variants))  # Remove duplicates
                })
        
        # Committee links
        if 'committees_info' in data:
            committees = data['committees_info'].get('committees', [])
            for committee in committees:
                system_code = committee.get('system_code')
                name = committee.get('name')
                if system_code and name:
                    committee_url = build_committee_url(system_code, name)
                    # Generate search variants for committees
                    variants = [name]
                    # Add shortened versions (e.g., "Committee on Armed Services" -> "Armed Services Committee")
                    if 'Committee on' in name:
                        short_name = name.replace('Committee on', '').strip() + ' Committee'
                        variants.append(short_name)
                    
                    links.append({
                        "text": name,
                        "url": committee_url,
                        "search_variants": variants
                    })
        
        # Cosponsor links (limited to first few)
        if 'cosponsors_info' in data:
            cosponsors = data['cosponsors_info'].get('cosponsors', [])
            for cosponsor in cosponsors[:5]:  # Limit to first 5
                bioguide = cosponsor.get('bioguide_id')
                name = cosponsor.get('name')
                party = cosponsor.get('party', '')
                state = cosponsor.get('state', '')
                
                if bioguide and name:
                    cosponsor_url = build_member_url(bioguide, name)
                    # Create full display name
                    full_name = name
                    if party and state:
                        full_name = f"{name} ({party}-{state})"
                    
                    variants = [name, full_name]
                    links.append({
                        "text": full_name,
                        "url": cosponsor_url,
                        "search_variants": list(set(variants))
                    })
        
        # Amendment sponsor links
        if 'amendments_info' in data:
            amendments = data['amendments_info'].get('amendments', [])
            for amendment in amendments:
                sponsor = amendment.get('sponsor', {})
                bioguide = sponsor.get('bioguide_id')
                name = sponsor.get('name')
                if bioguide and name:
                    amend_sponsor_url = build_member_url(bioguide, name)
                    variants = [name]
                    links.append({
                        "text": name,
                        "url": amend_sponsor_url,
                        "search_variants": variants
                    })
        
        return links

    def _validate_links_non_blocking(self, links):
        """Return ALL links immediately without validation to avoid empty hyperlinks."""
        # Skip validation entirely - congress.gov often blocks automated requests
        # Return all extracted links with search_variants
        return links

    async def _head_check(self, client: httpx.AsyncClient, link: dict) -> dict:
        url = link.get('url', '')
        try:
            # Use GET instead of HEAD - congress.gov blocks HEAD requests (403)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            resp = await client.get(url, follow_redirects=True, headers=headers)
            ok = resp.status_code == 200
        except Exception:
            ok = False
        return {**link, 'validated': ok}
    
    def run(self):
        """Start consuming messages"""
        logger.info("Question Worker started")
        
        for message in self.consumer:
            try:
                self.process_question(message.value)
            except Exception as e:
                logger.error(f"Error processing question: {e}", exc_info=True)

if __name__ == "__main__":
    worker = QuestionWorker()
    worker.run()
