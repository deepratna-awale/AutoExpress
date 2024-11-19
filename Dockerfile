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
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

# Default command to run the Flask app
CMD ["flask", "run"]
