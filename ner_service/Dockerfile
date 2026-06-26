FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Install torch CPU build (NER on CPU is fine; GPU reserved for the main stack).
RUN pip install --no-cache-dir torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Download the transformer-based English model (~430MB) into the image.
RUN python -m spacy download en_core_web_trf

COPY app.py .

EXPOSE 8500

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8500"]
