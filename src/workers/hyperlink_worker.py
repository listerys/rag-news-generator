import json
import logging
import asyncio
import httpx
from kafka import KafkaConsumer, KafkaProducer
from utils.validators import (
    validate_congress_url,
    build_member_url,
    build_committee_url,
    build_bill_url
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HyperlinkWorker:
    def __init__(self):
        self.consumer = KafkaConsumer(
            'hyperlink_tasks',
            bootstrap_servers='kafka:29092',
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='hyperlink_workers',
            auto_offset_reset='earliest'
        )
        
        self.producer = KafkaProducer(
            bootstrap_servers='kafka:29092',
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
    
    async def validate_links_async(self, links: list) -> list:
        """Validate multiple URLs asynchronously"""
        validated = []
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []
            
            for link in links:
                url = link.get('url', '')
                if url:
                    tasks.append(self._check_url(client, link))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, dict):
                    validated.append(result)
        
        return validated
    
    async def _check_url(self, client: httpx.AsyncClient, link: dict) -> dict:
        """Check if a single URL is valid"""
        url = link.get('url', '')
        
        try:
            # Use GET instead of HEAD - congress.gov blocks HEAD requests (403)
            # Set headers to mimic a browser to avoid blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = await client.get(url, follow_redirects=True, headers=headers)
            is_valid = response.status_code == 200
        except Exception as e:
            logger.warning(f"URL validation failed for {url}: {e}")
            is_valid = False
        
        return {
            **link,
            'validated': is_valid
        }
    
    def process_hyperlink_task(self, task):
        """Process hyperlink validation task"""
        bill_id = task.get('bill_id', '')
        links = task.get('links', [])
        
        logger.info(f"Validating {len(links)} links for {bill_id}")
        
        # Run async validation
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        validated_links = loop.run_until_complete(self.validate_links_async(links))
        loop.close()
        
        # Send validated links back
        result = {
            'bill_id': bill_id,
            'validated_links': validated_links,
            'task_type': 'validated_links'
        }
        
        self.producer.send('validated_links', value=result)
        self.producer.flush()
        
        logger.info(f"Validated links for {bill_id}")
    
    def run(self):
        """Start consuming hyperlink tasks"""
        logger.info("Hyperlink Worker started")
        
        for message in self.consumer:
            try:
                self.process_hyperlink_task(message.value)
            except Exception as e:
                logger.error(f"Error processing hyperlink task: {e}")


if __name__ == "__main__":
    worker = HyperlinkWorker()
    worker.run()
