FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir ultralytics opencv-python-headless lap numpy scipy imageio-ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY services/counting /app/services/counting
ENV PYTHONUNBUFFERED=1
CMD ["python", "services/counting/worker.py"]
