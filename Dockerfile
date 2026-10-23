# Use the official Python image and specify a version (e.g., 3.9-slim for a lighter image)
FROM python:3.10-slim

# Set working directory
WORKDIR /AutoExpress

# Copy the requirements file first to leverage Docker's caching for dependencies
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code, excluding files and folders defined in .dockerignore
COPY . .

# Expose the port Flask will run on
EXPOSE 5000

# Set environment variables for Flask
ENV FLASK_APP=autoexpress
ENV AUTOEXPRESS_HOST=0.0.0.0
ENV AUTOEXPRESS_PORT=5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4)"

# Serve with waitress (see autoexpress/__main__.py)
CMD ["python", "-m", "autoexpress"]
