FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget xz-utils libx11-6 libxi6 libxxf86vm1 libxrender1 \
    libxfixes3 libgl1-mesa-glx libegl1 libxkbcommon0 && \
    rm -rf /var/lib/apt/lists/*

# Install Blender 5.0
RUN wget -q https://download.blender.org/release/Blender5.0/blender-5.0.0-linux-x64.tar.xz -O /tmp/blender.tar.xz && \
    tar -xf /tmp/blender.tar.xz -C /opt/ && \
    rm /tmp/blender.tar.xz && \
    ln -s /opt/blender-5.0.0-linux-x64/blender /usr/local/bin/blender

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY app/ app/
COPY prompts/ prompts/

RUN mkdir -p data/sessions data/artifact_cache

ENV RING_VAL_BLENDER_EXECUTABLE=/usr/local/bin/blender
ENV PYTHONUNBUFFERED=1

EXPOSE 8104

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8104"]
