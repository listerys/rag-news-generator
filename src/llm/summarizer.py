"""
Simplified LLM-based question answering using Ollama
Replaced over-engineered validation system with clean, straightforward approach
"""
import logging
import os
import json
from typing import Dict
import ollama

logger = logging.getLogger(__name__)


class LLMSummarizer:
    def __init__(self):
        """Initialize Ollama client with qwen2.5:7b"""
        # Get Ollama host from environment, default to localhost
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

        self.client = ollama.Client(host=ollama_host)
        self.model = "qwen2.5:7b"
        logger.info(f"LLM Summarizer initialized with Ollama model: {self.model}")

    def answer_question(self, question: str, data: dict) -> str:
        """
        Generate a factual answer to a question based on provided data.
        
        Args:
            question: The question to answer
            data: Structured data from Congress API
            
        Returns:
            A clear, factual 2-4 sentence answer
        """
        try:
            # Create focused prompt
            prompt = self._create_prompt(question, data)

            # Generate answer with Ollama
            response = self.client.chat(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional congressional news reporter writing for the public. Write clear, engaging, and factual news reporting based only on the provided data. Use plain language that ordinary citizens can understand. Write in third person, be concise, and focus on what matters most to readers. If data is missing, acknowledge it naturally without sounding technical or apologetic."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                options={
                    "temperature": 0.4,  # Slightly higher for more natural language
                    "num_predict": 300,  # max_tokens equivalent in Ollama
                    "top_p": 0.9
                }
            )

            answer = response['message']['content'].strip()
            logger.debug(f"Generated answer: {answer[:100]}...")
            return answer
            
        except Exception as e:
            logger.error(f"Error generating answer: {e}", exc_info=True)
            return self._fallback_answer(question, data)

    def _create_prompt(self, question: str, data: dict) -> str:
        """
        Create a clean, focused prompt without over-engineering.
        """
        # Format data in a readable way
        context = self._format_data(data)
        
        # Extract names for hyperlinking
        hyperlink_entities = self._extract_entity_names(data)
        
        prompt = f"""You are reporting on a congressional bill for a news article. Answer this question in a journalistic style.

QUESTION: {question}

IMPORTANT NAMES (use these exact names exactly as shown):
{hyperlink_entities}

BILL DATA:
{context}

Write your answer in 2-4 sentences. Write as a journalist would for the general public - be clear, engaging, and focus on what matters. If specific data is unavailable, state that naturally without over-explaining why."""
        
        return prompt

    def _format_data(self, data: dict) -> str:
        """Format data into readable context, limiting size."""
        parts = []
        
        # Prioritize important fields
        priority_fields = [
            'bill_status',
            'sponsor_info', 
            'committees_info',
            'cosponsors_info',
            'votes_info',
            'amendments_info',
            'hearings_info',
            'committee_reports_info'
        ]
        
        for field in priority_fields:
            if field in data and data[field]:
                value = data[field]
                if isinstance(value, (dict, list)):
                    # Convert to JSON with size limit
                    json_str = json.dumps(value, indent=2)[:3000]
                    parts.append(f"{field}:\n{json_str}\n")
                else:
                    parts.append(f"{field}: {str(value)[:500]}\n")
        
        # Limit total context size
        context = "\n".join(parts)[:8000]
        return context if context else "(No data available)"

    def _extract_entity_names(self, data: dict) -> str:
        """Extract names of people and committees for hyperlinking."""
        entities = []
        
        # Sponsor
        if 'sponsor_info' in data and data['sponsor_info']:
            sponsor = data['sponsor_info']
            if isinstance(sponsor, dict) and sponsor.get('name'):
                entities.append(f"- Sponsor: {sponsor['name']}")
        
        # Committees (first 3)
        if 'committees_info' in data and data['committees_info']:
            committees = data['committees_info']
            if isinstance(committees, dict) and 'committees' in committees:
                for i, committee in enumerate(committees['committees'][:3]):
                    if committee.get('name'):
                        entities.append(f"- Committee: {committee['name']}")
        
        # Cosponsors (first 5)
        if 'cosponsors_info' in data and data['cosponsors_info']:
            cosponsors = data['cosponsors_info']
            if isinstance(cosponsors, dict) and 'cosponsors' in cosponsors:
                for cosponsor in cosponsors['cosponsors'][:5]:
                    if cosponsor.get('name'):
                        entities.append(f"- Cosponsor: {cosponsor['name']}")
        
        return "\n".join(entities) if entities else "(No specific names available)"

    def _fallback_answer(self, question: str, data: dict) -> str:
        """Provide a simple fallback answer when LLM fails."""
        # Try to extract basic facts
        if 'sponsor_info' in data and data['sponsor_info']:
            sponsor = data['sponsor_info']
            if isinstance(sponsor, dict) and sponsor.get('name'):
                return f"This legislation is sponsored by {sponsor['name']}."
        
        if 'bill_status' in data and data['bill_status']:
            status = data['bill_status']
            if isinstance(status, dict) and status.get('current_status'):
                return f"The bill's current status is: {status['current_status']}."
        
        return "Information on this aspect of the legislation is currently limited in congressional records."
