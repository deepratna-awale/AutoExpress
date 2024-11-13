# Use the official Python image and set it to support multiple architectures
FROM python:3

# Install Rust toolchain needed for some packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends cargo && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /AutoExpress/

# Copy the requirements file and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project into the container
COPY . .

# Expose the port that Flask will run on
EXPOSE 5000

# Set environment variable for Flask
ENV FLASK_APP=autoexpress
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

# Command to run the Flask app
CMD ["flask", "run"]
