# Deployment Guide - Suno Music Pipeline

## ✅ Pre-Deployment Checklist

- [ ] Python 3.9+ installed
- [ ] FFmpeg installed (`apt install ffmpeg` or `brew install ffmpeg`)
- [ ] FluidSynth installed (`apt install fluidsynth` or `brew install fluid-synth`)
- [ ] FluidR3_GM.sf2 SoundFont downloaded and placed in project root
- [ ] All Python dependencies installed (`pip install -r requirements.txt`)
- [ ] SOUNDFONT_PATH environment variable set (optional)
- [ ] Sufficient disk space for temp audio files
- [ ] Network connectivity for basic-pitch model download (first run only)

## 🚀 Quick Start (Development)

```bash
# 1. Clone the repository
git clone https://github.com/electronicsk710/suno-music-pipeline.git
cd suno-music-pipeline

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Download SoundFont
# Download from: https://member.keymusician.com/Member/FluidR3_GM/index.html
# Place FluidR3_GM.sf2 in project root

# 5. Run development server
uvicorn app:app --reload
```

Open `http://localhost:8000` in your browser.

---

## 🐳 Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fluidsynth \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY config.json .
COPY logger_config.py .
COPY static/ ./static/
COPY train/ ./train/
COPY FluidR3_GM.sf2 .

# Create logs directory
RUN mkdir -p logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Run application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Build and Run with Docker

```bash
# Build image
docker build -t suno-music-pipeline .

# Run container
docker run -p 8000:8000 \
  -e SOUNDFONT_PATH=/app/FluidR3_GM.sf2 \
  -v /path/to/uploads:/app/uploads \
  suno-music-pipeline
```

### Docker Compose

```yaml
version: '3.8'

services:
  music-pipeline:
    build: .
    ports:
      - "8000:8000"
    environment:
      - SOUNDFONT_PATH=/app/FluidR3_GM.sf2
    volumes:
      - ./logs:/app/logs
      - ./uploads:/app/uploads
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Run with: `docker-compose up -d`

---

## 🌐 Production Server Setup (Linux/Ubuntu)

### 1. Install System Dependencies

```bash
sudo apt update
sudo apt install -y python3.9 python3-pip python3-venv ffmpeg fluidsynth curl nginx supervisor
```

### 2. Setup Application

```bash
cd /opt
sudo git clone https://github.com/electronicsk710/suno-music-pipeline.git
cd suno-music-pipeline
sudo python3.9 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Download SoundFont

```bash
cd /opt/suno-music-pipeline
# Download FluidR3_GM.sf2 and place it here
sudo chown -R www-data:www-data /opt/suno-music-pipeline
```

### 4. Setup Supervisor (Process Management)

Create `/etc/supervisor/conf.d/suno-music-pipeline.conf`:

```ini
[program:suno-music-pipeline]
directory=/opt/suno-music-pipeline
command=/opt/suno-music-pipeline/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 2
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/suno-music-pipeline.log
environment=SOUNDFONT_PATH=/opt/suno-music-pipeline/FluidR3_GM.sf2
```

Then:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start suno-music-pipeline
```

### 5. Setup Nginx Reverse Proxy

Create `/etc/nginx/sites-available/suno-music-pipeline`:

```nginx
upstream suno_app {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;
    client_max_body_size 50M;

    location / {
        proxy_pass http://suno_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /static {
        alias /opt/suno-music-pipeline/static;
        expires 1d;
    }
}
```

Enable it:
```bash
sudo ln -s /etc/nginx/sites-available/suno-music-pipeline /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 6. Setup SSL/HTTPS (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 🧪 Testing the Deployment

### 1. Health Check Endpoint

```bash
curl http://localhost:8000/health
```

Expected response: `{"status": "healthy"}`

### 2. Manual Analysis Test

```bash
curl -X POST -F "file=@test_audio.wav" \
  http://localhost:8000/analyze
```

### 3. Load Testing (using wrk)

```bash
# Install wrk
sudo apt install wrk

# Test /analyze endpoint
wrk -t4 -c100 -d30s \
  -s upload_script.lua \
  http://localhost:8000/analyze
```

Create `upload_script.lua`:
```lua
request = function()
    wrk.method = "POST"
    wrk.body = "file=@test_audio.wav"
    wrk.headers["Content-Type"] = "multipart/form-data"
    return wrk.format(nil)
end
```

---

## 📊 Monitoring & Logging

### View Logs

```bash
# Tail live logs
tail -f logs/$(date +%Y%m%d).log

# Count errors
grep ERROR logs/$(date +%Y%m%d).log | wc -l
```

### Key Metrics to Monitor

- **Response time**: Target < 10s for analysis, < 15s for generation
- **Memory usage**: Typical peak ~500MB during MIDI rendering
- **Disk space**: Monitor temp file cleanup
- **CPU usage**: Should be < 80% under normal load
- **Error rate**: Target < 0.1% (1 in 1000 requests)

### Setup Monitoring with Prometheus

```python
# Add to app.py for Prometheus metrics
from prometheus_client import Counter, Histogram, generate_latest

analyze_counter = Counter('analyze_requests_total', 'Total analyze requests')
analyze_histogram = Histogram('analyze_duration_seconds', 'Time spent analyzing')
generate_counter = Counter('generate_requests_total', 'Total generate requests')
generate_histogram = Histogram('generate_duration_seconds', 'Time spent generating')

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

---

## 🔐 Security Best Practices

1. **Rate Limiting** - Add to protect against abuse:
```bash
pip install slowapi
```

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/analyze")
@limiter.limit("10/minute")
async def analyze_vocal(request: Request, file: UploadFile = File(...)):
    # ... endpoint code
```

2. **File Validation** - Validate uploaded audio files:
```python
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac', 'm4a'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

if file.filename.split('.')[-1].lower() not in ALLOWED_EXTENSIONS:
    raise HTTPException(status_code=400, detail="Invalid file type")
```

3. **Temporary File Cleanup** - Ensure temp files are cleaned:
```python
import atexit
import tempfile
import shutil

temp_dir = tempfile.gettempdir()
atexit.register(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
```

---

## 🆘 Troubleshooting

### Issue: "SoundFont not found"
**Solution**: Download FluidR3_GM.sf2 or set `SOUNDFONT_PATH` environment variable

### Issue: "CUDA out of memory" (if using GPU)
**Solution**: Reduce batch size or use CPU-only inference

### Issue: Slow inference
**Solution**: 
- Use CPU instead of GPU if GPU is overutilized
- Reduce sample rate (use 16kHz instead of 22050Hz)
- Cache models on first run

### Issue: Port 8000 already in use
**Solution**: 
```bash
lsof -i :8000  # Find what's using it
kill -9 <PID>  # Kill the process
# Or use different port: uvicorn app:app --port 8001
```

### Issue: Out of disk space
**Solution**: Check temp file cleanup
```bash
du -sh /tmp/
rm -rf /tmp/tmp*  # Be careful!
```

---

## 📈 Performance Optimization

### Caching Strategy
```python
from functools import lru_cache

@lru_cache(maxsize=32)
def get_diatonic_triads(key_name):
    # Cached chord triads per key
    pass
```

### Batch Processing
```python
# Process multiple files in queue
from queue import Queue
import threading

processing_queue = Queue()

def worker():
    while True:
        file = processing_queue.get()
        process_file(file)
        processing_queue.task_done()

for _ in range(4):  # 4 worker threads
    threading.Thread(target=worker, daemon=True).start()
```

### Async Processing
```python
@app.post("/generate")
async def generate_instrumental(req: GenerateRequest, background_tasks: BackgroundTasks):
    # Already uses background tasks for cleanup
    # Can extend with Celery for distributed processing
    pass
```

---

## ✅ Deployment Checklist

- [ ] All system dependencies installed
- [ ] Python dependencies installed
- [ ] SoundFont file present and path configured
- [ ] Logs directory created and writable
- [ ] Temp directory has sufficient space
- [ ] CORS configured if frontend is separate domain
- [ ] Rate limiting enabled
- [ ] Health check endpoint working
- [ ] SSL/HTTPS configured (production)
- [ ] Monitoring and logging setup
- [ ] Backup strategy for generated audio files
- [ ] Error notification alerts configured

---

## 🎯 Next Steps After Deployment

1. **Monitor performance** for first 24 hours
2. **Collect user feedback** on audio quality
3. **Analyze logs** for errors and optimization opportunities
4. **Fine-tune config.json** based on real usage patterns
5. **Consider model training** once you have production data

---

**Deployment Status**: 🟢 Ready for production testing!
