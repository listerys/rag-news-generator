import json
import logging
import time
from kafka import KafkaProducer
from database.state_store import StateStore
from congress_api.client import CongressAPIClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BILLS = [
    "H.R.1", "H.R.5371", "H.R.5401", 
    "S.2296", "S.24", "S.2882", "S.499",
    "S.Res.412", "H.Res.353", "H.R.1968"
]

QUESTIONS = [
    {
        "id": 1,
        "text": "What does this bill do? Where is it in the process?",
        "api_endpoints": ["bill_details", "actions"]
    },
    {
        "id": 2,
        "text": "What committees is this bill in?",
        "api_endpoints": ["committees"]
    },
    {
        "id": 3,
        "text": "Who is the sponsor?",
        "api_endpoints": ["sponsors"]
    },
    {
        "id": 4,
        "text": "Who cosponsored this bill? Are any on the committee?",
        "api_endpoints": ["cosponsors", "committees"]
    },
    {
        "id": 5,
        "text": "Have any hearings happened? What were findings?",
        "api_endpoints": ["committee_reports", "actions"]
    },
    {
        "id": 6,
        "text": "Have amendments been proposed? Who and what?",
        "api_endpoints": ["amendments"]
    },
    {
        "id": 7,
        "text": "Have votes happened? Party-line or bipartisan?",
        "api_endpoints": ["votes", "recorded_votes"]
    }
]

class Controller:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers='kafka:29092',
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        self.state_store = StateStore()
        self.api_client = CongressAPIClient()
        self.current_congress = self.api_client.get_current_congress()
        logger.info(f"Using Congress session: {self.current_congress}")
        
    def run(self):
        start_time = time.time()
        logger.info("Starting RAG News Generation Pipeline")
        
        # Create tasks for each bill
        for bill_id in BILLS:
            logger.info(f"Processing {bill_id}")
            
            # Normalize bill ID for API
            normalized_bill = self.normalize_bill_id(bill_id)
            
            # Check if already completed
            if self.state_store.is_bill_completed(bill_id):
                logger.info(f"{bill_id} already completed, skipping")
                continue
            
            # Create question tasks
            for question in QUESTIONS:
                task_message = {
                    "bill_id": bill_id,
                    "normalized_bill_id": normalized_bill,
                    "question_id": question["id"],
                    "question_text": question["text"],
                    "api_endpoints": question["api_endpoints"],
                    "task_type": "question_answering",
                    "timestamp": time.time()
                }
                
                self.producer.send('question_tasks', value=task_message)
                logger.info(f"Sent task: {bill_id} - Q{question['id']}")
        
        self.producer.flush()
        
        # Wait for all questions to be answered
        self.wait_for_completion()
        
        # Trigger article generation
        self.generate_articles()
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"Pipeline completed in {duration:.2f} seconds")
        self.log_benchmark(duration)
    
    def normalize_bill_id(self, bill_id):
        """Convert H.R.1 to hr1-118 format"""
        congress_session = self.current_congress
        bill_type_map = {
            "H.R.": "hr",
            "S.": "s",
            "H.Res.": "hres",
            "S.Res.": "sres",
            "H.J.Res.": "hjres",
            "S.J.Res.": "sjres",
            "H.Con.Res.": "hconres",
            "S.Con.Res.": "sconres"
        }
        
        for prefix, code in bill_type_map.items():
            if bill_id.startswith(prefix):
                number = bill_id.replace(prefix, "")
                return f"{code}{number}-{congress_session}"
        
        return bill_id.lower()
    
    def wait_for_completion(self):
        """Poll state store until all questions answered"""
        total_tasks = len(BILLS) * len(QUESTIONS)
        
        while True:
            completed = self.state_store.get_completed_count()
            logger.info(f"Progress: {completed}/{total_tasks} tasks completed")
            
            if completed >= total_tasks:
                break
            
            time.sleep(5)
    
    def generate_articles(self):
        """Send article generation tasks"""
        for bill_id in BILLS:
            task = {
                "bill_id": bill_id,
                "task_type": "article_generation",
                "timestamp": time.time()
            }
            self.producer.send('article_tasks', value=task)
        
        self.producer.flush()
        logger.info("Article generation tasks sent")
    
    def log_benchmark(self, duration):
        """Log performance metrics"""
        with open('/app/logs/benchmark.log', 'w') as f:
            f.write(f"Total Duration: {duration:.2f} seconds\n")
            f.write(f"Bills Processed: {len(BILLS)}\n")
            f.write(f"Average per Bill: {duration/len(BILLS):.2f} seconds\n")
            f.write(f"Questions per Bill: {len(QUESTIONS)}\n")

if __name__ == "__main__":
    controller = Controller()
    controller.run()
