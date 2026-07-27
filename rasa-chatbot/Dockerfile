FROM rasa/rasa:3.6.21-full

WORKDIR /app

# Copy requirements in case of custom dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Run Rasa
ENTRYPOINT []
CMD ["rasa", "run", "--enable-api", "--cors", "*"]
