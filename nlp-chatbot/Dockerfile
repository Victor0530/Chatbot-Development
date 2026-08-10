FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV NLTK_DATA=/usr/local/share/nltk_data
RUN python -m nltk.downloader -d $NLTK_DATA punkt punkt_tab stopwords wordnet omw-1.4

COPY . .
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8600"]
