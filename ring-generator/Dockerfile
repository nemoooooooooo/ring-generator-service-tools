FROM python:3.12-slim

# Blender dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget xz-utils libx11-6 libxi6 libxrender1 libgl1 libglib2.0-0 \
    libsm6 libxext6 libxkbcommon0 && \
    rm -rf /var/lib/apt/lists/*

# Install Blender 5.0
ARG BLENDER_URL=https://download.blender.org/release/Blender5.0/blender-5.0.0-linux-x64.tar.xz
RUN wget -q -O /tmp/blender.tar.xz ${BLENDER_URL} && \
    tar -xf /tmp/blender.tar.xz -C /opt && \
    rm /tmp/blender.tar.xz && \
    ln -s /opt/blender-5.0.0-linux-x64/blender /usr/local/bin/blender

ENV RING_GEN_BLENDER_EXECUTABLE=/usr/local/bin/blender

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY app/ app/
COPY prompts/ prompts/

ENV PYTHONUNBUFFERED=1

EXPOSE 8102

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8102"]
