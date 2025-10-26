"""
Markdown article builder
Assembles question answers into cohesive news-style articles
"""
import logging
from typing import Dict, List
import re

logger = logging.getLogger(__name__)


class MarkdownBuilder:
    def __init__(self):
        # Map questions to news-style section headers
        self.question_headers = {
            1: "## Overview",
            2: "## Committee Review",
            3: "## Legislative Sponsorship",
            4: "## Congressional Support",
            5: "## Committee Proceedings",
            6: "## Proposed Changes",
            7: "## Voting Record"
        }
    
    def build_article(self, bill_id: str, answers: Dict, metadata: Dict) -> Dict:
        """
        Build a complete news-style article from answers
        
        Args:
            bill_id: Bill identifier (e.g., "H.R.1")
            answers: Dict mapping question_id to {answer, hyperlinks}
            metadata: Dict with bill_title, sponsor_bioguide_id, committee_ids
            
        Returns:
            Dict matching required JSON schema
        """
        # Extract metadata
        bill_title = metadata.get('bill_title', bill_id)
        sponsor_bioguide = metadata.get('sponsor_bioguide_id', '')
        committee_ids = metadata.get('committee_ids', [])
        
        # Build article header
        article_lines = [
            f"# {bill_title}",
            f"*{bill_id}*",
            "",
        ]
        
        # Add each question's answer with proper formatting
        for q_id in sorted(answers.keys()):
            answer_data = answers[q_id]
            answer_text = answer_data.get('answer', '')
            hyperlinks = answer_data.get('hyperlinks', [])
            
            # Skip empty answers
            if not answer_text or answer_text.strip() == "":
                continue
            
            # Add section header
            header = self.question_headers.get(q_id, f"## Section {q_id}")
            article_lines.append(header)
            article_lines.append("")
            
            # Process answer text and insert hyperlinks
            formatted_answer = self._insert_hyperlinks(answer_text, hyperlinks)
            
            # Clean up any remaining technical phrases
            formatted_answer = self._clean_technical_language(formatted_answer)
            
            # Add the formatted answer
            article_lines.append(formatted_answer)
            article_lines.append("")
        
        # Combine into final article with proper newlines
        article_content = "\n".join(article_lines)
        
        # Return structured output matching required schema
        return {
            "bill_id": bill_id,
            "bill_title": bill_title,
            "sponsor_bioguide_id": sponsor_bioguide,
            "bill_committee_ids": committee_ids,
            "article_content": article_content
        }
    
    def _insert_hyperlinks(self, text: str, hyperlinks: List[Dict]) -> str:
        """Insert markdown hyperlinks into text intelligently with fuzzy matching"""
        if not hyperlinks:
            return text
        
        # Create mappings for both exact and fuzzy matches
        link_map = {}  # exact text -> url
        fuzzy_map = {}  # core name -> (full text, url)
        
        for link in hyperlinks:
            link_text = link.get('text', '').strip()
            link_url = link.get('url', '').strip()
            
            if not link_text or not link_url:
                continue
            
            # Use all links (validation skipped to avoid congress.gov blocking)
            link_map[link_text] = link_url
            
            # Extract core name variants for fuzzy matching
            # Handle patterns like "Rep. John Smith (D-CA-15)" -> "Rep. John Smith"
            core_name = re.sub(r'\s*\([^)]*\)\s*$', '', link_text).strip()
            if core_name != link_text and core_name:
                fuzzy_map[core_name] = (link_text, link_url)
            
            # Also store variants from search_variants if provided
            search_variants = link.get('search_variants', [])
            for variant in search_variants:
                variant = variant.strip()
                if variant and variant not in fuzzy_map:
                    fuzzy_map[variant] = (link_text, link_url)
        
        result = text
        already_linked = set()
        
        # First pass: exact matches (longest first)
        sorted_exact = sorted(link_map.keys(), key=len, reverse=True)
        for text_to_replace in sorted_exact:
            url = link_map[text_to_replace]
            
            # Check if already linked
            if f"[{text_to_replace}]" in result or text_to_replace in already_linked:
                continue
            
            # Replace first occurrence
            if text_to_replace in result:
                replacement = f"[{text_to_replace}]({url})"
                result = result.replace(text_to_replace, replacement, 1)
                already_linked.add(text_to_replace)
        
        # Second pass: fuzzy matches (for unlinked core names)
        sorted_fuzzy = sorted(fuzzy_map.keys(), key=len, reverse=True)
        for core_name in sorted_fuzzy:
            full_text, url = fuzzy_map[core_name]
            
            # Check if already linked or if full text was already linked
            if f"[{core_name}]" in result or core_name in already_linked:
                continue
            if full_text in already_linked:
                continue
            
            # Replace core name with link (use core name as display text)
            if core_name in result:
                replacement = f"[{core_name}]({url})"
                result = result.replace(core_name, replacement, 1)
                already_linked.add(core_name)
        
        return result
    
    def _clean_technical_language(self, text: str) -> str:
        """Remove technical jargon that shouldn't be in news articles"""
        # Remove technical phrases
        cleaned = text
        
        # Remove data completeness mentions
        cleaned = re.sub(r'\(Data completeness:.*?\)', '', cleaned)
        cleaned = re.sub(r'\*Note: Data completeness.*?\*', '', cleaned)
        cleaned = re.sub(r'Data completeness score:.*?/1\.0', '', cleaned)
        
        # Remove field references
        cleaned = re.sub(r'according to the \w+_info field', '', cleaned)
        cleaned = re.sub(r'according to \w+ field', '', cleaned)
        
        # Remove technical prefixes
        cleaned = cleaned.replace('Based on available data: ', '')
        cleaned = cleaned.replace('Based on available data, ', '')
        cleaned = cleaned.replace('Insufficient data available to provide specific details.', 
                                  'Further details are pending.')
        
        # Clean up multiple spaces and newlines
        cleaned = re.sub(r' +', ' ', cleaned)
        cleaned = re.sub(r'\n\n\n+', '\n\n', cleaned)
        
        return cleaned.strip()
    
    def format_list(self, items: List[str], bullet_char: str = "-") -> str:
        """Format a list as markdown"""
        if not items:
            return ""
        return "\n".join([f"{bullet_char} {item}" for item in items])
    
    def format_table(self, headers: List[str], rows: List[List[str]]) -> str:
        """Format data as markdown table"""
        if not headers or not rows:
            return ""
        
        lines = []
        
        # Header row
        lines.append("| " + " | ".join(headers) + " |")
        
        # Separator row
        lines.append("| " + " | ".join(["---" for _ in headers]) + " |")
        
        # Data rows
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
        
        return "\n".join(lines)
    
    def create_hyperlink(self, text: str, url: str) -> str:
        """Create a markdown hyperlink"""
        if not url:
            return text
        return f"[{text}]({url})"
    
    def sanitize_markdown(self, text: str) -> str:
        """Sanitize text for markdown (escape special characters if needed)"""
        # Just strip extra whitespace
        return " ".join(text.split())
