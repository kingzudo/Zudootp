FROM python:3.11-slim

WORKDIR /app

COPY otp.py .

RUN pip install --no-cache-dir python-telegram-bot pyrogram tgcrypto qrcode[pil]

CMD ["python", "otp.py"]
