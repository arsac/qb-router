FROM python:3.14-rc-alpine

RUN apk add --no-cache rsync

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/. .

CMD ["python", "./main.py"]