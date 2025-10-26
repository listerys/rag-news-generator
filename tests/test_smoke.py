import pytest
import json
import os

def test_articles_generated():
    """Verify all 10 articles were generated"""
    assert os.path.exists('/app/output/articles.json')
    
    with open('/app/output/articles.json', 'r') as f:
        articles = json.load(f)
    
    assert len(articles) == 10

def test_article_structure():
    """Verify article schema"""
    with open('/app/output/articles.json', 'r') as f:
        articles = json.load(f)
    
    required_fields = ['bill_id', 'bill_title', 'sponsor_bioguide_id', 
                       'bill_committee_ids', 'article_content']
    
    for article in articles:
        for field in required_fields:
            assert field in article

def test_hyperlinks_present():
    """Verify articles contain hyperlinks"""
    with open('/app/output/articles.json', 'r') as f:
        articles = json.load(f)
    
    for article in articles:
        content = article['article_content']
        assert '](https://www.congress.gov' in content

def test_performance():
    """Verify completion time under 10 minutes"""
    with open('/app/logs/benchmark.log', 'r') as f:
        first_line = f.readline()
        duration = float(first_line.split(':')[1].split()[0])
    
    assert duration < 600  # 10 minutes
