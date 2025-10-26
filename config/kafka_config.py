"""
Kafka Configuration
"""
import os

# Kafka Broker Configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092')
KAFKA_CLIENT_ID = 'rag-news-generator'

# Topic Names
TOPICS = {
    'question_tasks': 'question_tasks',
    'hyperlink_tasks': 'hyperlink_tasks',
    'validated_links': 'validated_links',
    'article_tasks': 'article_tasks',
}

# Consumer Configuration
CONSUMER_CONFIG = {
    'bootstrap_servers': KAFKA_BOOTSTRAP_SERVERS,
    'auto_offset_reset': 'earliest',
    'enable_auto_commit': True,
    'auto_commit_interval_ms': 1000,
    'session_timeout_ms': 30000,
    'max_poll_records': 10,
}

# Producer Configuration
PRODUCER_CONFIG = {
    'bootstrap_servers': KAFKA_BOOTSTRAP_SERVERS,
    'acks': 'all',
    'retries': 3,
    'max_in_flight_requests_per_connection': 5,
    'compression_type': 'gzip',
}

# Consumer Groups
CONSUMER_GROUPS = {
    'question_workers': 'question_workers',
    'hyperlink_workers': 'hyperlink_workers',
    'article_generators': 'article_generators',
}

# Topic Configurations
TOPIC_CONFIGS = {
    'question_tasks': {
        'num_partitions': 7,  # One per question type
        'replication_factor': 1,
    },
    'hyperlink_tasks': {
        'num_partitions': 3,
        'replication_factor': 1,
    },
    'validated_links': {
        'num_partitions': 1,
        'replication_factor': 1,
    },
    'article_tasks': {
        'num_partitions': 1,
        'replication_factor': 1,
    },
}

# Message Schema Templates
MESSAGE_SCHEMAS = {
    'question_task': {
        'bill_id': str,
        'normalized_bill_id': str,
        'question_id': int,
        'question_text': str,
        'api_endpoints': list,
        'task_type': str,
        'timestamp': float,
    },
    'hyperlink_task': {
        'bill_id': str,
        'links': list,
        'task_type': str,
        'timestamp': float,
    },
    'article_task': {
        'bill_id': str,
        'task_type': str,
        'timestamp': float,
    },
}
