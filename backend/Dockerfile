FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libreoffice-core \
    libreoffice-writer \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    tesseract-ocr-guj \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install PyTorch with CUDA 12.1 wheels FIRST so pip resolver picks the GPU build.
# The non-torch lines in requirements.txt then install from PyPI normally.
RUN pip install --no-cache-dir \
    torch==2.2.2 torchvision==0.17.2 \
    --index-url https://download.pytorch.org/whl/cu121

RUN pip install --no-cache-dir -r requirements.txt

# Cross-document face matching (photo-superimposition / mixed-identity detection).
# --no-deps so it CANNOT disturb the pinned CUDA torch above; its runtime deps
# (torch/torchvision/numpy/pillow/requests) are already installed.
RUN pip install --no-cache-dir --no-deps facenet-pytorch==2.6.0

# Bake the FaceNet (VGGFace2) weights into the image so face matching runs fully
# OFFLINE with no first-use download. MTCNN's weights ship inside the package.
RUN python -c "from facenet_pytorch import InceptionResnetV1; InceptionResnetV1(pretrained='vggface2'); print('vggface2 weights cached')"

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
