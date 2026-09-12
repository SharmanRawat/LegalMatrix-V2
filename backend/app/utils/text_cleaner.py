import re

def clean_text(text):
    """Clean OCR text for better extraction"""
    # Remove special characters that cause issues
    text = re.sub(r'[°®™©]', '', text)
    # Normalize multiple spaces
    text = re.sub(r'\s+', ' ', text)
    # Remove non-printable characters
    text = ''.join(char for char in text if char.isprintable())
    return text.strip()