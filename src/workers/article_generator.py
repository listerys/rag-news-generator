import json
import logging
from kafka import KafkaConsumer
from database.state_store import StateStore
from utils.markdown_builder import MarkdownBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ArticleGenerator:
    def __init__(self):
        self.consumer = KafkaConsumer(
            'article_tasks',
            bootstrap_servers='kafka:29092',
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='article_generators',
            auto_offset_reset='earliest'
        )
        
        self.state_store = StateStore()
        self.markdown_builder = MarkdownBuilder()
        self.articles = []
    
    def generate_article(self, task):
        """Generate article for a bill"""
        bill_id = task['bill_id']
        
        logger.info(f"Generating article for {bill_id}")
        
        # Retrieve all answers
        answers = self.state_store.get_all_answers(bill_id)
        
        if len(answers) < 7:
            logger.warning(f"Incomplete answers for {bill_id}: {len(answers)}/7")
            return
        
        # Retrieve bill metadata
        metadata = self.state_store.get_bill_metadata(bill_id)
        
        if not metadata:
            logger.error(f"No metadata found for {bill_id}")
            return
        
        # Build article
        article = self.markdown_builder.build_article(bill_id, answers, metadata)
        
        # Save article
        self.articles.append(article)
        self.save_articles()
        
        logger.info(f"Article generated for {bill_id}")
    
    def save_articles(self):
        """Save all articles to JSON"""
        with open('/app/output/articles.json', 'w') as f:
            json.dump(self.articles, f, indent=2)
    
    def run(self):
        """Start consuming article generation tasks"""
        logger.info("Article Generator started")
        
        for message in self.consumer:
            try:
                self.generate_article(message.value)
            except Exception as e:
                logger.error(f"Error generating article: {e}")

if __name__ == "__main__":
    generator = ArticleGenerator()
    generator.run()
