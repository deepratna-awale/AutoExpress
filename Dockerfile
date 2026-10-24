# Build the Next.js frontend into static files
FROM node:26-slim AS frontend
WORKDIR /frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ .
RUN pnpm build

# Use the official Python image and specify a version (e.g., 3.9-slim for a lighter image)
FROM python:3.13-slim

# Run as an unprivileged user with uid 1000 (what Hugging Face Spaces expect),
# so the app, its Output/uploads folders and the rembg model cache are writable
RUN useradd --create-home --uid 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    U2NET_HOME=/home/user/.u2net

# Set working directory
WORKDIR /AutoExpress
RUN chown user:user /AutoExpress

# Copy the requirements file first to leverage Docker's caching for dependencies
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

USER user

# rembg models to download at build time (space separated, e.g. "isnet-anime u2net_human_seg").
# Empty downloads each one on first use instead.
ARG PRELOAD_REMBG_MODELS=""
RUN for model in $PRELOAD_REMBG_MODELS; do \
        python -c "import sys; from rembg import new_session; new_session(sys.argv[1])" "$model" || exit 1; \
    done

# Copy the rest of the application code, excluding files and folders defined in .dockerignore
COPY --chown=user:user . .
COPY --chown=user:user --from=frontend /frontend/out ./frontend/out

# Expose the port Flask will run on
EXPOSE 5000

# Set environment variables for Flask
ENV FLASK_APP=autoexpress
ENV AUTOEXPRESS_HOST=0.0.0.0
ENV AUTOEXPRESS_PORT=5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('AUTOEXPRESS_PORT', '5000'), timeout=4)"

# Serve with waitress (see autoexpress/__main__.py)
CMD ["python", "-m", "autoexpress"]
