FROM python:3

# Set working directory
WORKDIR /

# Copy the requirements file and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project into the container
COPY . .

# Expose the port that Flask will run on
EXPOSE 5000

# Set environment variable for Flask (optional but recommended)
ENV FLASK_APP=autoexpress

# Command to run the Flask app, ensure it's available externally
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
