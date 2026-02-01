# Python slim image use kar (lightweight)
FROM python:3.11-slim

# Working directory set kar
WORKDIR /app

# Bot script copy kar
COPY otp.py .

# Required library install kar (tere bot me jo imports hain uske hisab se)
# python-telegram-bot + pyrogram + qrcode + pillow (QR ke liye)
RUN pip install --no-cache-dir \
    python-telegram-bot \
    pyrogram \
    tgcrypto \
    qrcode[pil]

# Bot run kar
CMD ["python", "otp.py"]
