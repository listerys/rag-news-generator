"""
Enhanced parsers for Congress.gov API responses with comprehensive data extraction
"""
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def parse_bill_status(bill_data: Dict, actions_data: Dict) -> Dict:
    """Extract comprehensive legislative status with accurate tracking"""
    result = {
        'title': '',
        'summary': '',
        'current_status': 'Introduced',
        'latest_action': '',
        'latest_action_date': '',
        'public_law_number': '',
        'house_passage': {},
        'senate_passage': {},
        'presidential_action': '',
        'cloture_attempts': [],
        'status_details': ''
    }
    
    try:
        bill = bill_data.get('bill', {})
        result['title'] = bill.get('title', '')
        
        # Check if bill has become law (from bill object itself)
        laws = bill.get('laws', [])
        if laws and isinstance(laws, list) and len(laws) > 0:
            law = laws[0]
            law_type = law.get('type', '')
            law_number = law.get('number', '')
            if law_type and law_number:
                result['public_law_number'] = f"{law_type} {law_number}"
                result['current_status'] = 'Became Law'
        
        # Get summary
        summaries = bill.get('summaries', [])
        if summaries and isinstance(summaries, list) and len(summaries) > 0:
            result['summary'] = summaries[0].get('text', '')[:500]  # Limit length
        elif summaries and isinstance(summaries, dict):
            # Sometimes summaries is a dict, not a list
            result['summary'] = summaries.get('text', '')[:500]
        
        # Get latest action
        actions = actions_data.get('actions', [])
        if actions and len(actions) > 0:
            latest = actions[0]
            result['latest_action'] = latest.get('text', '')
            result['latest_action_date'] = latest.get('actionDate', '')
        
        # Analyze ALL actions for comprehensive status (most recent first)
        house_passed = False
        senate_passed = False
        became_law = (result['current_status'] == 'Became Law')  # Already detected from bill object
        vetoed = False
        tabled = False
        failed_cloture_count = 0
        
        for action in actions:
            action_text = action.get('text', '')
            action_lower = action_text.lower()
            action_date = action.get('actionDate', '')
            
            # Check for Public Law (highest priority)
            if 'became public law' in action_lower or 'public law no:' in action_lower:
                became_law = True
                # Extract law number
                law_match = re.search(r'public law no[.:]\s*(\d+-\d+)', action_lower)
                if law_match:
                    result['public_law_number'] = f"Public Law {law_match.group(1)}"
                result['current_status'] = 'Became Law'
                result['status_details'] = f"Enacted on {action_date}"
            
            # Check for veto
            if 'vetoed by president' in action_lower or 'pocket veto' in action_lower:
                vetoed = True
                if not became_law:  # Veto not overridden
                    result['current_status'] = 'Vetoed'
                    result['status_details'] = action_text
            
            # Check for Presidential action
            if 'signed by president' in action_lower:
                result['presidential_action'] = action_text
                if not became_law:
                    result['current_status'] = 'Signed by President'
            elif 'presented to president' in action_lower and not result['presidential_action']:
                result['presidential_action'] = action_text
                if not became_law and not vetoed:
                    result['current_status'] = 'Sent to President'
            
            # Check for motion to table (kills the bill)
            if 'motion to table' in action_lower and 'agreed to' in action_lower:
                tabled = True
                if not became_law:
                    result['current_status'] = 'Tabled (Blocked)'
                    result['status_details'] = f"Tabled on {action_date}"
            
            # House passage - extract vote counts
            if ('passed house' in action_lower or 'passed/agreed to in house' in action_lower) and not house_passed:
                house_passed = True
                vote_match = re.search(r'(\d+)\s*[-/]\s*(\d+)', action_text)
                result['house_passage'] = {
                    'date': action_date,
                    'text': action_text,
                    'yea': vote_match.group(1) if vote_match else '',
                    'nay': vote_match.group(2) if vote_match else ''
                }
                if not became_law and not vetoed and not tabled:
                    result['current_status'] = 'Passed House'
                    result['status_details'] = f"Passed House {result['house_passage']['yea']}-{result['house_passage']['nay']} on {action_date}"
            
            # Senate passage - extract vote counts
            if ('passed senate' in action_lower or 'passed/agreed to in senate' in action_lower) and not senate_passed:
                senate_passed = True
                vote_match = re.search(r'(\d+)\s*[-/]\s*(\d+)', action_text)
                result['senate_passage'] = {
                    'date': action_date,
                    'text': action_text,
                    'yea': vote_match.group(1) if vote_match else '',
                    'nay': vote_match.group(2) if vote_match else ''
                }
                if house_passed and not became_law and not vetoed:
                    result['current_status'] = 'Passed Both Chambers'
                    result['status_details'] = f"Passed both chambers, awaiting presidential action"
                elif not became_law and not vetoed and not tabled:
                    result['current_status'] = 'Passed Senate'
                    result['status_details'] = f"Passed Senate {result['senate_passage']['yea']}-{result['senate_passage']['nay']} on {action_date}"
            
            # Track failed cloture (indicates blocked legislation)
            if 'cloture' in action_lower and ('not invoked' in action_lower or 'failed' in action_lower):
                failed_cloture_count += 1
                result['cloture_attempts'].append({
                    'date': action_date,
                    'result': 'Failed',
                    'description': action_text[:150]
                })
                # Only set status if no passage has occurred
                if not house_passed and not senate_passed and not became_law:
                    if failed_cloture_count == 1:
                        result['current_status'] = 'Cloture Failed (1 attempt)'
                    else:
                        result['current_status'] = f'Cloture Failed ({failed_cloture_count} attempts)'
                    result['status_details'] = f"Unable to proceed due to failed cloture votes"
            
            # Track successful cloture
            if 'cloture' in action_lower and ('invoked' in action_lower or 'agreed to' in action_lower):
                result['cloture_attempts'].append({
                    'date': action_date,
                    'result': 'Passed',
                    'description': action_text[:150]
                })
        
        # If no passage detected and not explicitly blocked, check committee/floor status
        if not house_passed and not senate_passed and not became_law and not tabled and failed_cloture_count == 0:
            # Check recent actions for current location
            for action in actions[:10]:  # Check more recent actions
                action_lower = action.get('text', '').lower()
                
                if 'placed on' in action_lower and 'calendar' in action_lower:
                    result['current_status'] = 'On Calendar (Awaiting Floor Action)'
                    break
                elif 'reported' in action_lower and 'committee' in action_lower:
                    result['current_status'] = 'Reported from Committee'
                    break
                elif 'ordered to be reported' in action_lower:
                    result['current_status'] = 'Ordered to be Reported'
                    break
                elif 'referred to' in action_lower and 'committee' in action_lower:
                    result['current_status'] = 'In Committee'
                    break
        
        # Check origin chamber
        origin = bill.get('originChamber', '')
        result['origin_chamber'] = origin
        
        logger.info(f"Bill status: {result['current_status']} (House: {house_passed}, Senate: {senate_passed}, Law: {became_law})")
        
    except Exception as e:
        logger.error(f"Error parsing bill status: {e}", exc_info=True)
    
    return result


def parse_sponsor_info(bill_data: Dict) -> Dict:
    """Extract sponsor details and bioguide ID"""
    result = {
        'name': '',
        'bioguide_id': '',
        'state': '',
        'party': '',
        'url': ''
    }
    
    try:
        bill = bill_data.get('bill', {})
        sponsors = bill.get('sponsors', [])
        
        if sponsors and len(sponsors) > 0:
            sponsor = sponsors[0]
            result['name'] = sponsor.get('fullName', '')
            result['bioguide_id'] = sponsor.get('bioguideId', '')
            result['state'] = sponsor.get('state', '')
            result['party'] = sponsor.get('party', '')
            result['url'] = sponsor.get('url', '')
        
    except Exception as e:
        logger.error(f"Error parsing sponsor info: {e}")
    
    return result


def parse_cosponsors(cosponsors_data: Dict, committees_data: Dict) -> Dict:
    """List cosponsors with accurate count"""
    result = {
        'total_count': 0,
        'cosponsors': [],
        'withdrawn_count': 0
    }
    
    try:
        cosponsors = cosponsors_data.get('cosponsors', [])
        
        # Count active vs withdrawn
        active_cosponsors = []
        withdrawn_count = 0
        
        for cosponsor in cosponsors:
            if cosponsor.get('sponsorshipWithdrawnDate'):
                withdrawn_count += 1
            else:
                active_cosponsors.append(cosponsor)
        
        result['total_count'] = len(active_cosponsors)
        result['withdrawn_count'] = withdrawn_count
        
        # Extract detailed info for first 50 active cosponsors
        for cosponsor in active_cosponsors[:50]:
            result['cosponsors'].append({
                'name': cosponsor.get('fullName', ''),
                'bioguide_id': cosponsor.get('bioguideId', ''),
                'state': cosponsor.get('state', ''),
                'party': cosponsor.get('party', ''),
                'sponsored_date': cosponsor.get('sponsorshipDate', '')
            })
        
    except Exception as e:
        logger.error(f"Error parsing cosponsors: {e}")
    
    return result


def parse_committees(committees_data: Dict) -> Dict:
    """Extract committee names and system codes"""
    result = {
        'committees': [],
        'committee_ids': []
    }
    
    try:
        committees = committees_data.get('committees', [])
        
        for committee in committees:
            system_code = committee.get('systemCode', '')
            name = committee.get('name', '')
            chamber = committee.get('chamber', '')
            
            result['committees'].append({
                'name': name,
                'system_code': system_code,
                'chamber': chamber,
                'url': committee.get('url', '')
            })
            
            if system_code:
                result['committee_ids'].append(system_code)
        
    except Exception as e:
        logger.error(f"Error parsing committees: {e}")
    
    return result


def parse_amendments(amendments_data: Dict) -> Dict:
    """Extract amendment summary with complete counts by status"""
    result = {
        'total_count': 0,
        'adopted_count': 0,
        'rejected_count': 0,
        'pending_count': 0,
        'withdrawn_count': 0,
        'actual_total_from_api': 0,
        'notable_amendments': []  # First 10 for context
    }
    
    try:
        amendments = amendments_data.get('amendments', [])
        result['total_count'] = len(amendments)
        
        # Get actual total from pagination if available
        pagination = amendments_data.get('pagination', {})
        if pagination and 'total_actual' in pagination:
            result['actual_total_from_api'] = pagination['total_actual']
        
        # Count by status
        for amendment in amendments:
            latest_action = amendment.get('latestAction', {}).get('text', '').lower()
            
            if 'agreed to' in latest_action or 'adopted' in latest_action or 'amendment agreed' in latest_action:
                result['adopted_count'] += 1
            elif 'rejected' in latest_action or 'failed' in latest_action or 'not agreed to' in latest_action:
                result['rejected_count'] += 1
            elif 'withdrawn' in latest_action:
                result['withdrawn_count'] += 1
            else:
                result['pending_count'] += 1
        
        # Extract details for first 15 amendments for better context
        for amendment in amendments[:15]:
            amend_info = {
                'number': amendment.get('number', ''),
                'description': (amendment.get('description', '') or amendment.get('purpose', ''))[:200],
                'sponsor': {},
                'submitted_date': amendment.get('submittedDate', ''),
                'status': amendment.get('latestAction', {}).get('text', '')[:150]
            }
            
            # Get sponsor if available
            sponsors = amendment.get('sponsors', [])
            if sponsors and len(sponsors) > 0:
                sponsor = sponsors[0]
                amend_info['sponsor'] = {
                    'name': sponsor.get('fullName', ''),
                    'party': sponsor.get('party', ''),
                    'state': sponsor.get('state', '')
                }
            
            result['notable_amendments'].append(amend_info)
        
        logger.info(f"Parsed {result['total_count']} amendments (API total: {result['actual_total_from_api']}, adopted: {result['adopted_count']}, rejected: {result['rejected_count']}, pending: {result['pending_count']})")
        
    except Exception as e:
        logger.error(f"Error parsing amendments: {e}")
    
    return result


def parse_votes(actions_data: Dict) -> Dict:
    """Extract detailed vote information with accurate type classification"""
    result = {
        'total_votes': 0,
        'votes': [],
        'passage_votes': 0,
        'cloture_votes': 0,
        'procedural_votes': 0,
        'amendment_votes': 0,
        'motion_to_table_votes': 0
    }
    
    try:
        actions = actions_data.get('actions', [])
        
        for action in actions:
            action_text = action.get('text', '')
            action_lower = action_text.lower()
            
            # Look for recorded votes
            recorded_votes = action.get('recordedVotes', [])
            
            for vote in recorded_votes:
                # Extract vote counts from action text
                vote_match = re.search(r'(\d+)\s*[-/]\s*(\d+)', action_text)
                
                vote_info = {
                    'date': action.get('actionDate', ''),
                    'description': action_text,
                    'chamber': vote.get('chamber', ''),
                    'roll_number': vote.get('rollNumber', ''),
                    'url': vote.get('url', ''),
                    'yea_count': vote_match.group(1) if vote_match else '',
                    'nay_count': vote_match.group(2) if vote_match else '',
                    'result': '',
                    'vote_type': '',
                    'vote_subtype': '',
                    'is_final_passage': False,
                    'priority': 5  # Default priority (lower = more important)
                }
                
                # Determine result with more precision
                if 'passed' in action_lower or 'agreed to' in action_lower:
                    vote_info['result'] = 'Passed'
                elif 'failed' in action_lower or 'rejected' in action_lower or 'defeated' in action_lower:
                    vote_info['result'] = 'Failed'
                elif 'not invoked' in action_lower:
                    vote_info['result'] = 'Not Invoked'
                
                # Classify vote type with better detection
                if 'cloture' in action_lower:
                    vote_info['vote_type'] = 'Cloture Motion'
                    vote_info['priority'] = 3  # Medium priority (procedural but important)
                    result['cloture_votes'] += 1
                    if 'not invoked' in action_lower or 'failed' in action_lower:
                        vote_info['result'] = 'Failed (Cloture Not Invoked)'
                    else:
                        vote_info['result'] = 'Passed (Cloture Invoked)'
                    # Specify what the cloture was for
                    if 'motion to proceed' in action_lower:
                        vote_info['vote_subtype'] = 'Cloture on Motion to Proceed'
                    elif 'amendment' in action_lower:
                        vote_info['vote_subtype'] = 'Cloture on Amendment'
                    else:
                        vote_info['vote_subtype'] = 'Cloture on Measure'
                
                elif 'motion to table' in action_lower:
                    vote_info['vote_type'] = 'Motion to Table'
                    vote_info['vote_subtype'] = 'Procedural'
                    result['motion_to_table_votes'] += 1
                    result['procedural_votes'] += 1
                    if 'agreed to' in action_lower:
                        vote_info['result'] = 'Tabled (Motion Agreed To)'
                    
                elif 'passage' in action_lower or 'final passage' in action_lower:
                    vote_info['vote_type'] = 'Final Passage'
                    vote_info['is_final_passage'] = True
                    vote_info['priority'] = 1  # Highest priority
                    result['passage_votes'] += 1
                    if 'house' in action_lower:
                        vote_info['vote_subtype'] = 'House Final Passage'
                    elif 'senate' in action_lower:
                        vote_info['vote_subtype'] = 'Senate Final Passage'
                        
                elif 'motion to proceed' in action_lower:
                    vote_info['vote_type'] = 'Motion to Proceed'
                    vote_info['vote_subtype'] = 'Procedural'
                    result['procedural_votes'] += 1
                    
                elif 'amendment' in action_lower:
                    vote_info['vote_type'] = 'Amendment Vote'
                    result['amendment_votes'] += 1
                    # Extract amendment number if present
                    amend_match = re.search(r'amendment[s]?\s+(no\.\s*)?(\d+)', action_lower)
                    if amend_match:
                        vote_info['vote_subtype'] = f'Amendment {amend_match.group(2)}'
                        
                elif 'veto override' in action_lower:
                    vote_info['vote_type'] = 'Veto Override'
                    vote_info['vote_subtype'] = 'Constitutional'
                    
                elif 'motion to recommit' in action_lower or 'motion to reconsider' in action_lower:
                    vote_info['vote_type'] = 'Procedural Motion'
                    vote_info['vote_subtype'] = action_text[:50]  # Capture specific motion
                    result['procedural_votes'] += 1
                    
                elif 'concur' in action_lower or 'conference report' in action_lower:
                    vote_info['vote_type'] = 'Conference/Concurrence'
                    vote_info['vote_subtype'] = 'Agreement on Changes'
                    
                else:
                    vote_info['vote_type'] = 'Vote on Measure'
                
                # Determine if party-line or bipartisan based on vote margin
                # NOTE: Without actual party-by-party voting records, we can only infer partisanship
                # from supermajorities. Close margins do NOT necessarily indicate bipartisanship.
                if vote_match:
                    yea = int(vote_match.group(1))
                    nay = int(vote_match.group(2))
                    margin = abs(yea - nay)
                    total = yea + nay

                    if total > 0:
                        yea_pct = yea / total
                        margin_pct = margin / total

                        # Only classify as bipartisan if there's a supermajority (67%+)
                        # This is a strong indicator of cross-party support
                        if yea_pct >= 0.67:
                            vote_info['partisan_nature'] = 'Bipartisan (supermajority)'
                        elif yea_pct <= 0.33:
                            vote_info['partisan_nature'] = 'Bipartisan rejection (supermajority)'
                        # For other margins, describe the vote margin without assuming partisanship
                        elif margin_pct < 0.05:
                            vote_info['partisan_nature'] = 'Very close vote'
                        elif margin_pct < 0.15:
                            vote_info['partisan_nature'] = 'Close vote'
                        else:
                            vote_info['partisan_nature'] = 'Divided vote'
                
                result['votes'].append(vote_info)

        # Sort votes by priority (final passage votes first)
        result['votes'].sort(key=lambda v: v.get('priority', 999))

        result['total_votes'] = len(result['votes'])

        logger.info(f"Parsed {result['total_votes']} votes: {result['passage_votes']} passage, {result['cloture_votes']} cloture, {result['procedural_votes']} procedural")
        
    except Exception as e:
        logger.error(f"Error parsing votes: {e}")
    
    return result


def parse_hearings(actions_data: Dict) -> Dict:
    """Extract comprehensive hearing and committee meeting information"""
    result = {
        'total_hearings': 0,
        'hearings': [],
        'markup_sessions': 0,
        'committee_meetings': 0,
        'floor_consideration': 0,
        'subcommittee_actions': 0
    }
    
    try:
        actions = actions_data.get('actions', [])
        
        for action in actions:
            action_text = action.get('text', '')
            action_lower = action_text.lower()
            action_date = action.get('actionDate', '')

            # EXCLUDE votes - they should only appear in votes_info, not hearings_info
            # Check for recorded votes or vote-related keywords
            has_recorded_vote = action.get('recordedVotes', []) and len(action.get('recordedVotes', [])) > 0
            is_vote_action = any(keyword in action_lower for keyword in [
                'vote:', 'roll call', 'roll no.', 'passed house', 'passed senate',
                'final passage', 'yea-nay', 'record vote', 'on passage',
                'motion to table', 'cloture', 'veto override'
            ])

            if has_recorded_vote or is_vote_action:
                continue  # Skip votes - they're handled by parse_votes()

            # Look for various types of committee and floor proceedings
            is_hearing = 'hearing' in action_lower and 'committee' in action_lower
            is_markup = ('markup' in action_lower or 'ordered to be reported' in action_lower or 
                        'committee ordered' in action_lower or 'reported to' in action_lower)
            is_meeting = ('committee consideration' in action_lower or 'committee meeting' in action_lower or
                         'committee agreed' in action_lower or 'considered by' in action_lower)
            is_subcommittee = 'subcommittee' in action_lower
            is_floor = ('floor' in action_lower and 'consideration' in action_lower) or 'placed on' in action_lower
            
            # Also look for reported actions which indicate committee work
            is_reported = 'reported' in action_lower and 'committee' in action_lower
            
            if is_hearing or is_markup or is_meeting or is_reported or is_subcommittee or is_floor:
                hearing_info = {
                    'date': action_date,
                    'description': action_text,
                    'committee': '',
                    'type': ''
                }
                
                # Determine type with priority order
                if is_subcommittee and is_hearing:
                    hearing_info['type'] = 'Subcommittee Hearing'
                    result['subcommittee_actions'] += 1
                elif is_subcommittee:
                    hearing_info['type'] = 'Subcommittee Action'
                    result['subcommittee_actions'] += 1
                elif is_markup:
                    hearing_info['type'] = 'Committee Markup'
                    result['markup_sessions'] += 1
                elif is_reported:
                    hearing_info['type'] = 'Reported by Committee'
                    result['markup_sessions'] += 1
                elif is_hearing:
                    hearing_info['type'] = 'Committee Hearing'
                elif is_floor:
                    hearing_info['type'] = 'Floor Consideration'
                    result['floor_consideration'] += 1
                elif is_meeting:
                    hearing_info['type'] = 'Committee Meeting'
                    result['committee_meetings'] += 1
                else:
                    hearing_info['type'] = 'Committee Action'
                    result['committee_meetings'] += 1
                
                # Extract committee name
                committees = action.get('committees', [])
                if committees and len(committees) > 0:
                    hearing_info['committee'] = committees[0].get('name', '')
                
                # Try to extract from text if not in structured data
                if not hearing_info['committee']:
                    # Look for committee mentions in text
                    committee_patterns = [
                        r'Committee on ([\w\s,]+)',
                        r'([\w\s]+) Committee',
                        r'reported to ([\w\s]+) with'
                    ]
                    for pattern in committee_patterns:
                        match = re.search(pattern, action_text, re.IGNORECASE)
                        if match:
                            hearing_info['committee'] = match.group(1).strip()
                            break
                
                result['hearings'].append(hearing_info)
        
        result['total_hearings'] = len(result['hearings'])
        
        logger.info(f"Parsed {result['total_hearings']} committee/floor actions: {result['markup_sessions']} markups, {result['committee_meetings']} meetings, {result['floor_consideration']} floor actions")
        
    except Exception as e:
        logger.error(f"Error parsing hearings: {e}")
    
    return result


def parse_committee_reports(reports_data: Dict) -> Dict:
    """Extract committee reports which contain hearing findings and analysis"""
    result = {
        'total_reports': 0,
        'reports': []
    }
    
    try:
        reports = reports_data.get('reports', [])
        result['total_reports'] = len(reports)
        
        for report in reports[:5]:  # Limit to first 5 most relevant reports
            report_info = {
                'citation': report.get('citation', ''),
                'type': report.get('type', ''),
                'date': report.get('updateDate', ''),
                'title': (report.get('text', '') or '')[:200],
                'chamber': '',
                'url': report.get('url', '')
            }
            
            # Extract chamber from citation if present (e.g., "H. Rept. 119-1" or "S. Rept. 119-1")
            citation = report_info['citation']
            if citation:
                if citation.startswith('H.'):
                    report_info['chamber'] = 'House'
                elif citation.startswith('S.'):
                    report_info['chamber'] = 'Senate'
            
            result['reports'].append(report_info)
        
        logger.info(f"Parsed {result['total_reports']} committee reports")
        
    except Exception as e:
        logger.error(f"Error parsing committee reports: {e}")
    
    return result


def extract_bill_metadata(bill_data: Dict, committees_data: Dict) -> Dict:
    """Extract metadata needed for final article JSON"""
    metadata = {
        'bill_title': '',
        'sponsor_bioguide_id': '',
        'committee_ids': []
    }
    
    try:
        # Get title
        bill = bill_data.get('bill', {})
        metadata['bill_title'] = bill.get('title', '')
        
        # Get sponsor bioguide
        sponsors = bill.get('sponsors', [])
        if sponsors and len(sponsors) > 0:
            metadata['sponsor_bioguide_id'] = sponsors[0].get('bioguideId', '')
        
        # Get committee IDs
        committees = committees_data.get('committees', [])
        metadata['committee_ids'] = [
            c.get('systemCode', '') for c in committees if c.get('systemCode')
        ]
        
    except Exception as e:
        logger.error(f"Error extracting bill metadata: {e}")
    
    return metadata
