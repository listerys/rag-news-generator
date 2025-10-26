import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import json

logger = logging.getLogger(__name__)

class StateStore:
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL', 'postgresql://raguser:ragpass@localhost:5432/ragdb')
        self.conn = None
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Establish database connection with retries"""
        import time
        max_retries = 5
        for i in range(max_retries):
            try:
                self.conn = psycopg2.connect(self.database_url)
                logger.info("Database connection established")
                return
            except Exception as e:
                logger.warning(f"Database connection attempt {i+1}/{max_retries} failed: {e}")
                time.sleep(2)
        
        raise Exception("Failed to connect to database")
    
    def _create_tables(self):
        """Create necessary tables if they don't exist"""
        with self.conn.cursor() as cur:
            # Task completion tracking
            cur.execute("""
                CREATE TABLE IF NOT EXISTS task_completion (
                    bill_id VARCHAR(50),
                    question_id INTEGER,
                    completed BOOLEAN DEFAULT FALSE,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bill_id, question_id)
                )
            """)
            
            # Answer storage
            cur.execute("""
                CREATE TABLE IF NOT EXISTS answers (
                    id SERIAL PRIMARY KEY,
                    bill_id VARCHAR(50),
                    question_id INTEGER,
                    answer_text TEXT,
                    hyperlinks JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (bill_id, question_id)
                )
            """)
            
            # Bill metadata
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bill_metadata (
                    bill_id VARCHAR(50) PRIMARY KEY,
                    bill_title TEXT,
                    sponsor_bioguide_id VARCHAR(20),
                    committee_ids JSONB,
                    normalized_bill_id VARCHAR(50),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            self.conn.commit()
            logger.info("Database tables created/verified")
    
    def is_question_completed(self, bill_id: str, question_id: int) -> bool:
        """Check if a specific question has been completed"""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT completed FROM task_completion WHERE bill_id = %s AND question_id = %s",
                (bill_id, question_id)
            )
            result = cur.fetchone()
            return result and result[0]
    
    def mark_question_complete(self, bill_id: str, question_id: int):
        """Mark a question as completed"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO task_completion (bill_id, question_id, completed)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (bill_id, question_id) 
                DO UPDATE SET completed = TRUE, completed_at = CURRENT_TIMESTAMP
            """, (bill_id, question_id))
            self.conn.commit()
            logger.info(f"Marked {bill_id} Q{question_id} as complete")
    
    def save_answer(self, bill_id: str, question_id: int, answer_text: str, hyperlinks: list):
        """Save answer with hyperlinks"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO answers (bill_id, question_id, answer_text, hyperlinks)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (bill_id, question_id)
                DO UPDATE SET answer_text = EXCLUDED.answer_text, 
                             hyperlinks = EXCLUDED.hyperlinks,
                             created_at = CURRENT_TIMESTAMP
            """, (bill_id, question_id, answer_text, json.dumps(hyperlinks)))
            self.conn.commit()
            logger.debug(f"Saved answer for {bill_id} Q{question_id}")
    
    def get_all_answers(self, bill_id: str) -> dict:
        """Retrieve all answers for a bill"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT question_id, answer_text, hyperlinks
                FROM answers
                WHERE bill_id = %s
                ORDER BY question_id
            """, (bill_id,))
            
            results = cur.fetchall()
            answers = {}
            for row in results:
                answers[row['question_id']] = {
                    'answer': row['answer_text'],
                    'hyperlinks': row['hyperlinks']
                }
            return answers
    
    def get_completed_count(self) -> int:
        """Get total number of completed tasks"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM task_completion WHERE completed = TRUE")
            result = cur.fetchone()
            return result[0] if result else 0
    
    def is_bill_completed(self, bill_id: str) -> bool:
        """Check if all questions for a bill are completed"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM task_completion 
                WHERE bill_id = %s AND completed = TRUE
            """, (bill_id,))
            result = cur.fetchone()
            return result and result[0] >= 7  # All 7 questions completed
    
    def save_bill_metadata(self, bill_id: str, title: str, sponsor_bioguide: str, 
                          committee_ids: list, normalized_bill_id: str):
        """Save bill metadata for article generation, handling missing data gracefully"""
        # Provide defaults for missing critical fields
        if not title or title.strip() == "":
            title = bill_id  # Use bill_id as fallback title
            logger.warning(f"No title found for {bill_id}, using bill_id as title")
        
        if not sponsor_bioguide or sponsor_bioguide.strip() == "":
            sponsor_bioguide = ""
            logger.warning(f"No sponsor bioguide ID found for {bill_id}")
        
        if not committee_ids:
            committee_ids = []
            logger.info(f"No committees found for {bill_id} (may be normal for some resolutions)")
        
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bill_metadata 
                (bill_id, bill_title, sponsor_bioguide_id, committee_ids, normalized_bill_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (bill_id)
                DO UPDATE SET 
                    bill_title = EXCLUDED.bill_title,
                    sponsor_bioguide_id = EXCLUDED.sponsor_bioguide_id,
                    committee_ids = EXCLUDED.committee_ids,
                    normalized_bill_id = EXCLUDED.normalized_bill_id,
                    updated_at = CURRENT_TIMESTAMP
            """, (bill_id, title, sponsor_bioguide, json.dumps(committee_ids), normalized_bill_id))
            self.conn.commit()
            logger.info(f"Saved metadata for {bill_id}: title='{title[:50]}...', sponsor='{sponsor_bioguide}', committees={len(committee_ids)}")
    
    def get_bill_metadata(self, bill_id: str) -> dict:
        """Get bill metadata"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM bill_metadata WHERE bill_id = %s",
                (bill_id,)
            )
            result = cur.fetchone()
            return dict(result) if result else {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
