"""Print the Gemini models your API key can use (run: python list_models.py)."""
from google import genai

from app.core.config import settings

client = genai.Client(api_key=settings.gemini_api_key)
for m in client.models.list():
    if "flash" in m.name and "generateContent" in (m.supported_actions or []):
        print(m.name.removeprefix("models/"))
