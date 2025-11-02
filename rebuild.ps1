# Complete rebuild script for RAG News Generator
# This script stops everything, removes all caches, and rebuilds from scratch

Write-Host "=== Stopping all services ===" -ForegroundColor Yellow
docker-compose down

Write-Host "`n=== Removing old images ===" -ForegroundColor Yellow
docker-compose rm -f

Write-Host "`n=== Removing database volume (old state) ===" -ForegroundColor Yellow
docker volume rm rag-news-generator_postgres_data -ErrorAction SilentlyContinue

Write-Host "`n=== Clearing Redis cache ===" -ForegroundColor Yellow
# Start Redis temporarily to clear cache
docker-compose up -d redis
Start-Sleep -Seconds 5
docker-compose exec redis redis-cli FLUSHALL
docker-compose stop redis

Write-Host "`n=== Building fresh images (no cache) ===" -ForegroundColor Yellow
docker-compose build --no-cache

Write-Host "`n=== Starting infrastructure services ===" -ForegroundColor Yellow
docker-compose up -d zookeeper kafka postgres redis ollama

Write-Host "`n=== Waiting for services to initialize (30 seconds) ===" -ForegroundColor Yellow
Start-Sleep -Seconds 30

Write-Host "`n=== Verifying qwen2.5:7b model ===" -ForegroundColor Yellow
docker exec rag-news-generator-ollama-1 ollama list

Write-Host "`n=== Starting application services ===" -ForegroundColor Yellow
docker-compose up -d question_worker controller article_generator hyperlink_worker

Write-Host "`n=== Setup complete! Monitor with: docker-compose logs -f question_worker ===" -ForegroundColor Green
