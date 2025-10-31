import logging
import os
import json
import time
import requests
from typing import Dict, Any, List, Optional, Tuple
import hashlib


logger = logging.getLogger(__name__)


class LLMSummarizer:
    def __init__(self):
        """Initialize enhanced Ollama client with anti-hallucination measures"""
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.model = os.getenv("LLM_MODEL", "llama3.1:8b")
        self.max_retries = 3
        self.base_delay = 1
        self.confidence_threshold = 0.7  # Minimum confidence for assertions
        
        # Test connection
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            response.raise_for_status()
            logger.info(f"Enhanced LLM Summarizer initialized (model: {self.model})")
        except Exception as e:
            logger.warning(f"Could not connect to Ollama at {self.ollama_url}: {e}")

    def verify_data_completeness(self, data: dict) -> Dict[str, Any]:
        """Pre-check data completeness and flag missing critical information"""
        completeness_report = {
            "missing_fields": [],
            "empty_fields": [],
            "questionable_values": [],
            "data_quality_score": 1.0
        }
        
        # Critical fields that should not be missing
        critical_fields = ['sponsor_info', 'committees_info', 'bill_status', '_raw']
        
        for field in critical_fields:
            if field not in data:
                completeness_report["missing_fields"].append(field)
                completeness_report["data_quality_score"] -= 0.15
            elif not data[field] or (isinstance(data[field], (list, dict)) and len(data[field]) == 0):
                completeness_report["empty_fields"].append(field)
                completeness_report["data_quality_score"] -= 0.1
        
        # Check for suspicious numerical values
        if 'cosponsors_info' in data and isinstance(data['cosponsors_info'], dict):
            cosponsor_count = data['cosponsors_info'].get('total_count', 0)
            if cosponsor_count > 400:  # Unlikely to have more than 400 cosponsors
                completeness_report["questionable_values"].append("cosponsor_count_high")
        
        return completeness_report

    def extract_factual_claims(self, data: dict) -> List[Dict[str, Any]]:
        """Extract specific factual claims from the data for verification"""
        claims = []
        
        # Extract bill status information (CRITICAL)
        if 'bill_status' in data and data['bill_status']:
            status_info = data['bill_status']
            if isinstance(status_info, dict):
                current_status = status_info.get('current_status', '')
                if current_status:
                    claims.append({
                        "type": "status",
                        "claim": f"Current status: {current_status}",
                        "evidence": status_info,
                        "confidence": 0.95
                    })
                
                # Add public law info if available
                public_law = status_info.get('public_law_number', '')
                if public_law:
                    claims.append({
                        "type": "law",
                        "claim": f"Became {public_law}",
                        "evidence": {"law_number": public_law},
                        "confidence": 0.99
                    })
                
                # Add passage information
                if status_info.get('house_passage'):
                    hp = status_info['house_passage']
                    if hp.get('yea') and hp.get('nay'):
                        claims.append({
                            "type": "vote",
                            "claim": f"Passed House {hp['yea']}-{hp['nay']}",
                            "evidence": hp,
                            "confidence": 0.95
                        })
                
                if status_info.get('senate_passage'):
                    sp = status_info['senate_passage']
                    if sp.get('yea') and sp.get('nay'):
                        claims.append({
                            "type": "vote",
                            "claim": f"Passed Senate {sp['yea']}-{sp['nay']}",
                            "evidence": sp,
                            "confidence": 0.95
                        })
        
        # Extract sponsor information
        if 'sponsor_info' in data and data['sponsor_info']:
            sponsor_info = data['sponsor_info']
            if isinstance(sponsor_info, dict) and 'name' in sponsor_info:
                claims.append({
                    "type": "sponsor",
                    "claim": f"Sponsored by {sponsor_info['name']}",
                    "evidence": sponsor_info,
                    "confidence": 0.9 if sponsor_info['name'] else 0.3
                })
        
        # Extract committee information
        if 'committees_info' in data and data['committees_info']:
            committees = data['committees_info']
            if isinstance(committees, dict) and 'committees' in committees:
                for committee in committees['committees'][:3]:  # Limit to first 3
                    if 'name' in committee:
                        claims.append({
                            "type": "committee",
                            "claim": f"Referred to {committee['name']}",
                            "evidence": committee,
                            "confidence": 0.8
                        })
        
        # Extract vote information
        if 'votes_info' in data and data['votes_info']:
            votes = data['votes_info']
            if isinstance(votes, dict) and 'votes' in votes:
                for vote in votes['votes'][:2]:  # Limit to first 2 votes
                    if 'result' in vote:
                        claims.append({
                            "type": "vote",
                            "claim": f"Vote result: {vote['result']}",
                            "evidence": vote,
                            "confidence": 0.9
                        })
        
        # Extract numerical claims
        if 'cosponsors_info' in data:
            cosponsors_data = data['cosponsors_info']
            if isinstance(cosponsors_data, dict):
                cosponsor_count = cosponsors_data.get('total_count', 0)
                if cosponsor_count == 0 and 'cosponsors' in cosponsors_data:
                    cosponsor_count = len(cosponsors_data['cosponsors']) if isinstance(cosponsors_data['cosponsors'], list) else 0
                claims.append({
                    "type": "count",
                    "claim": f"Has {cosponsor_count} cosponsors",
                    "evidence": {"count": cosponsor_count, "source": "cosponsors_info"},
                    "confidence": 0.9
                })

        # NEW: Extract amendment claims
        if 'amendments_info' in data:
            amends = data['amendments_info']
            if isinstance(amends, dict):
                total = amends.get('total_count', 0)
                adopted = amends.get('adopted_count', 0)
                rejected = amends.get('rejected_count', 0)
                pending = amends.get('pending_count', 0)
                if total > 0:
                    claims.append({
                        "type": "amendment_count",
                        "claim": f"{total} amendments proposed ({adopted} adopted, {rejected} rejected, {pending} pending)",
                        "evidence": amends,
                        "confidence": 0.9
                    })
                # Extract specific amendment details
                notable_amendments = amends.get('notable_amendments', [])
                for amend in notable_amendments[:3]:  # Top 3 amendments
                    amend_num = amend.get('number', '')
                    amend_sponsor = amend.get('sponsor', {})
                    sponsor_name = amend_sponsor.get('name', '') if isinstance(amend_sponsor, dict) else ''
                    if amend_num and sponsor_name:
                        claims.append({
                            "type": "amendment_detail",
                            "claim": f"Amendment {amend_num} by {sponsor_name}",
                            "evidence": amend,
                            "confidence": 0.85
                        })

        # NEW: Extract hearing claims
        if 'hearings_info' in data:
            hearings = data['hearings_info']
            if isinstance(hearings, dict):
                total = hearings.get('total_hearings', 0)
                markup = hearings.get('markup_sessions', 0)
                meetings = hearings.get('committee_meetings', 0)
                if total > 0:
                    claims.append({
                        "type": "hearings",
                        "claim": f"{total} committee actions/hearings ({markup} markups, {meetings} meetings)",
                        "evidence": hearings,
                        "confidence": 0.85
                    })
                # Extract specific hearing details
                hearing_list = hearings.get('hearings', [])
                for hearing in hearing_list[:3]:  # Top 3 hearings
                    h_type = hearing.get('type', '')
                    h_date = hearing.get('date', '')
                    h_committee = hearing.get('committee', '')
                    if h_type and h_date:
                        claim_text = f"{h_type} on {h_date}"
                        if h_committee:
                            claim_text += f" by {h_committee}"
                        claims.append({
                            "type": "hearing_detail",
                            "claim": claim_text,
                            "evidence": hearing,
                            "confidence": 0.8
                        })

        # NEW: Extract committee reports claims
        if 'committee_reports_info' in data:
            reports = data['committee_reports_info']
            if isinstance(reports, dict):
                total = reports.get('total_reports', 0)
                if total > 0:
                    claims.append({
                        "type": "committee_reports",
                        "claim": f"{total} committee reports published",
                        "evidence": reports,
                        "confidence": 0.9
                    })

        return claims

    def _extract_hyperlink_entities(self, data: dict) -> str:
        """Extract entity names that should be used for hyperlinking"""
        entities = []
        
        # Extract sponsor name
        if 'sponsor_info' in data and data['sponsor_info']:
            sponsor = data['sponsor_info']
            if isinstance(sponsor, dict) and 'name' in sponsor:
                name = sponsor.get('name', '')
                if name:
                    entities.append(f"- Sponsor: {name}")
        
        # Extract committee names
        if 'committees_info' in data and data['committees_info']:
            committees = data['committees_info']
            if isinstance(committees, dict) and 'committees' in committees:
                committee_list = committees['committees']
                if committee_list:
                    committee_names = [c.get('name', '') for c in committee_list[:3] if c.get('name')]
                    if committee_names:
                        entities.append(f"- Committees: {', '.join(committee_names)}")
        
        # Extract cosponsor names (first few)
        if 'cosponsors_info' in data and data['cosponsors_info']:
            cosponsors = data['cosponsors_info']
            if isinstance(cosponsors, dict) and 'cosponsors' in cosponsors:
                cosponsor_list = cosponsors['cosponsors']
                if cosponsor_list:
                    cosponsor_names = [c.get('name', '') for c in cosponsor_list[:3] if c.get('name')]
                    if cosponsor_names:
                        entities.append(f"- Cosponsors: {', '.join(cosponsor_names)}")
        
        if not entities:
            return "(No specific entities identified for hyperlinking)"
        
        return "\n".join(entities)

    def create_grounded_prompt(self, question: str, data: dict, claims: List[Dict[str, Any]], completeness_report: Dict[str, Any] = None) -> str:
        """Create a prompt that explicitly grounds responses in provided data"""

        # NEW: Pre-filter votes to prioritize final passage votes for vote-related questions
        if 'votes_info' in data and 'vote' in question.lower():
            votes_info = data['votes_info'].copy()
            all_votes = votes_info.get('votes', [])

            # Separate final passage votes from procedural votes
            final_passage_votes = [v for v in all_votes if v.get('is_final_passage')]
            other_votes = [v for v in all_votes if not v.get('is_final_passage')]

            # Rebuild votes_info with final passage first (limit to most important votes)
            votes_info['votes'] = final_passage_votes[:5] + other_votes[:3]
            data = data.copy()
            data['votes_info'] = votes_info
            logger.info(f"Filtered votes: {len(final_passage_votes)} final passage, {len(other_votes)} other")

        # Format verified claims
        verified_facts = []
        for claim in claims:
            if claim["confidence"] >= self.confidence_threshold:
                verified_facts.append(f"• {claim['claim']}")

        # Extract available entities for hyperlinking
        hyperlink_entities = self._extract_hyperlink_entities(data)

        # Create constrained context
        context = self.format_constrained_context(data)

        # NEW: Add data quality warning if needed
        data_quality_warning = ""
        if completeness_report and completeness_report['data_quality_score'] < 0.7:
            data_quality_warning = """
IMPORTANT: The data provided is incomplete. Be especially careful to:
- Only state facts explicitly present in the data
- Acknowledge when information is limited
- Do NOT infer or extrapolate missing details
"""

        prompt = f"""You are a congressional news reporter writing for a professional publication. Write in a clear, engaging news style.
{data_quality_warning}

CRITICAL RULES:
1. ONLY use information explicitly provided in the data below
2. Write naturally - like a news article, not a technical report
3. DO NOT include technical phrases like "Data completeness", "confidence score", "according to field X"
4. If critical information is missing, acknowledge it briefly and naturally
   Example: "Committee assignments for this bill are not yet available in congressional records."
5. If NO information exists to answer the question, say so clearly and briefly
   Example: "Details on hearings have not been published at this time."
6. NEVER invent or infer information not explicitly in the data
7. Use exact names, dates, and numbers as provided - do not approximate or round
8. When you have partial information, report what IS available without mentioning what's missing

SPECIAL INSTRUCTIONS FOR VOTES:
- When reporting votes, ALWAYS prioritize FINAL PASSAGE votes (look for is_final_passage: True or vote_type: "Final Passage")
- Final passage votes are the most important - these are votes on passing the actual bill
- Ignore committee votes (usually low numbers like 10-9) unless no passage votes exist
- Report the partisan_nature field accurately (e.g., "Bipartisan (supermajority)", "Close vote", "Divided vote")
- Do NOT call a vote "bipartisan" unless the data explicitly says so

IMPORTANT - NAMES TO USE FOR HYPERLINKING:
When mentioning these people or entities, use these EXACT names so they can be hyperlinked:
{hyperlink_entities}

VERIFIED INFORMATION:
{chr(10).join(verified_facts) if verified_facts else "Limited information available - write based on what data exists"}

QUESTION: {question}

SOURCE DATA:
{context}

Write a clear, news-style response (2-4 sentences). Be direct and factual. If data is limited, focus on what IS available without mentioning what's missing.

Response:"""
        
        return prompt

    def format_constrained_context(self, data: dict) -> str:
        """Format data with explicit field names and structure preservation"""
        context_parts = []

        for key, value in data.items():
            if isinstance(value, dict):
                # Preserve structure and show field names
                if value:  # Only include non-empty dicts
                    dict_str = json.dumps({k: v for k, v in value.items() if v}, indent=2)[:2000]
                    context_parts.append(f"Field '{key}': {dict_str}")
                else:
                    context_parts.append(f"Field '{key}': [EMPTY]")
            elif isinstance(value, list):
                if len(value) > 0:
                    # Show count and sample data
                    list_preview = json.dumps(value[:3], indent=2)[:1500]
                    context_parts.append(f"Field '{key}' (count: {len(value)}): {list_preview}")
                else:
                    context_parts.append(f"Field '{key}': [EMPTY LIST]")
            else:
                if value:
                    context_parts.append(f"Field '{key}': {str(value)[:1000]}")
                else:
                    context_parts.append(f"Field '{key}': [EMPTY]")

        return "\n\n".join(context_parts)[:12000]  # Increased from 3500 to support richer context (Llama 3.1 8B supports 8K+ tokens)

    def answer_question(self, question: str, data: dict) -> str:
        """Generate answer with enhanced hallucination prevention"""

        # Step 1: Verify data completeness
        completeness_report = self.verify_data_completeness(data)
        logger.info(f"Data quality score: {completeness_report['data_quality_score']:.2f}")

        # NEW: Data quality guardrails - reject if data is severely incomplete
        if completeness_report['data_quality_score'] < 0.5:
            logger.warning(f"Data quality too low ({completeness_report['data_quality_score']:.2f}) - returning graceful fallback")
            return "Information on this topic is limited in congressional records at this time."

        # Step 2: Extract factual claims
        factual_claims = self.extract_factual_claims(data)

        # Step 3: Create grounded prompt with quality-based adjustments
        prompt = self.create_grounded_prompt(question, data, factual_claims, completeness_report)
        
        # Step 4: Generate with multiple attempts and consistency checking
        responses = []
        for attempt in range(min(2, self.max_retries)):  # Generate 2 responses for consistency check
            try:
                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.2,  # Lower temperature for more deterministic outputs
                            "num_predict": 250,
                            "top_p": 0.9,
                            "repeat_penalty": 1.1,
                            "seed": 42 if attempt == 0 else 43  # Different seed for variation
                        }
                    },
                    timeout=120
                )
                
                response.raise_for_status()
                result = response.json()
                answer = result.get("response", "").strip()
                
                if answer:
                    responses.append(answer)
                    logger.info(f"Generated response {attempt + 1} ({len(answer)} chars)")
                
            except Exception as e:
                logger.error(f"Generation attempt {attempt + 1} failed: {e}")
        
        # Step 5: Select best response or combine if consistent
        if len(responses) >= 2:
            final_answer = self.select_best_response(responses, factual_claims)
        elif len(responses) == 1:
            final_answer = responses[0]
        else:
            final_answer = self._enhanced_fallback_answer(question, data, completeness_report)
        
        # Step 6: Post-process for final quality check
        final_answer = self.post_process_answer(final_answer, data, completeness_report)
        
        return final_answer

    def select_best_response(self, responses: List[str], claims: List[Dict[str, Any]]) -> str:
        """Select the response that best aligns with verified claims"""
        # Simple heuristic: prefer the response that mentions more verified facts
        scores = []
        
        for response in responses:
            score = 0
            for claim in claims:
                if claim["confidence"] >= self.confidence_threshold:
                    # Check if key elements of the claim appear in the response
                    claim_words = claim["claim"].lower().split()
                    response_lower = response.lower()
                    if any(word in response_lower for word in claim_words if len(word) > 3):
                        score += claim["confidence"]
            scores.append(score)
        
        # Return response with highest score
        best_idx = scores.index(max(scores)) if scores else 0
        return responses[best_idx]

    def post_process_answer(self, answer: str, data: dict, completeness_report: Dict[str, Any]) -> str:
        """Final quality check and enhancement of the answer"""
        
        # Log data quality internally but don't add to public output
        if completeness_report["data_quality_score"] < 0.8:
            logger.info(f"Data quality score: {completeness_report['data_quality_score']:.1f}/1.0")
            if completeness_report["missing_fields"]:
                logger.info(f"Missing fields: {', '.join(completeness_report['missing_fields'])}")
        
        # Check for potential hallucination markers
        hallucination_markers = [
            "john smith", "jane doe", "unknown sponsor", "approximately", "roughly",
            "data completeness", "confidence score", "based on available data:",
            "information not available in provided data", "according to.*field"
        ]
        
        answer_lower = answer.lower()
        for marker in hallucination_markers:
            if marker in answer_lower:
                logger.warning(f"Potential hallucination/technical marker detected: {marker}")
        
        # Remove any accidental technical phrases that slipped through
        answer = answer.replace("(Data completeness:", "").replace("/1.0)", "")
        answer = answer.replace("Based on available data: ", "")
        answer = answer.replace("*Note: Data completeness score:", "")
        
        return answer.strip()

    def _enhanced_fallback_answer(self, question: str, data: dict, completeness_report: Dict[str, Any]) -> str:
        """Enhanced fallback when LLM generation fails - write natural news-style responses"""
        
        # Try to extract basic facts directly from data and write naturally
        parts = []
        
        if 'sponsor_info' in data and data['sponsor_info']:
            sponsor = data['sponsor_info']
            if isinstance(sponsor, dict) and 'name' in sponsor and sponsor['name']:
                name = sponsor['name']
                party = sponsor.get('party', '')
                state = sponsor.get('state', '')
                if party and state:
                    parts.append(f"{name} ({party}-{state})")
                else:
                    parts.append(name)
        
        if 'committees_info' in data and data['committees_info']:
            committees = data['committees_info']
            if isinstance(committees, dict) and 'committees' in committees:
                committee_names = [c.get('name', '') for c in committees['committees'][:2] if c.get('name')]
                if committee_names:
                    if len(committee_names) == 1:
                        parts.append(f"has been referred to the {committee_names[0]}")
                    else:
                        parts.append(f"has been referred to the {committee_names[0]} and {committee_names[1]}")
        
        # Build natural sentence
        if parts:
            if 'sponsor_info' in data and parts[0]:
                if len(parts) > 1:
                    base_answer = f"The legislation is sponsored by {parts[0]} and {parts[1]}."
                else:
                    base_answer = f"The legislation is sponsored by {parts[0]}."
            else:
                base_answer = ". ".join(parts) + "."
        else:
            # When no data available, acknowledge gracefully like a reporter would
            base_answer = "Details on this aspect of the legislation are not currently available in congressional records."
        
        # Log completeness internally
        if completeness_report["data_quality_score"] < 0.9:
            logger.info(f"Fallback used. Data completeness: {completeness_report['data_quality_score']:.1f}/1.0")
        
        return base_answer

    def batch_verify_responses(self, responses: List[str], original_data: List[dict]) -> List[Dict[str, Any]]:
        """Batch verification of multiple responses against source data"""
        verification_results = []
        
        for i, (response, data) in enumerate(zip(responses, original_data)):
            result = {
                "response_id": i,
                "verification_score": 0.0,
                "flagged_issues": [],
                "confidence_assessment": "low"
            }
            
            # Extract claims from generated response for verification
            claims = self.extract_factual_claims(data)
            verified_count = 0
            total_verifiable = len(claims)
            
            for claim in claims:
                if claim["confidence"] >= self.confidence_threshold:
                    # Simple verification: check if claim elements appear in response
                    if any(word in response.lower() for word in claim["claim"].lower().split() if len(word) > 3):
                        verified_count += 1
            
            if total_verifiable > 0:
                result["verification_score"] = verified_count / total_verifiable
            
            # Confidence assessment
            if result["verification_score"] >= 0.8:
                result["confidence_assessment"] = "high"
            elif result["verification_score"] >= 0.6:
                result["confidence_assessment"] = "medium"
            else:
                result["confidence_assessment"] = "low"
            
            verification_results.append(result)
        
        return verification_results
