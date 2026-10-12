"""Small provider-agnostic helper: send a text prompt, get a JSON object back."""
import json

from google import genai
from google.genai import types
from openai import AsyncOpenAI

from app.core.config import settings


class LLMError(Exception):
    pass


async def ask_json(prompt: str) -> dict:
    try:
        if settings.ai_provider == "gemini":
            if not settings.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set in .env")
            client = genai.Client(api_key=settings.gemini_api_key)
            response = await client.aio.models.generate_content(
                model=settings.gemini_model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
            )
            text = response.text
        elif settings.ai_provider == "groq":
            if not settings.groq_api_key:
                raise LLMError("GROQ_API_KEY is not set in .env")
            client = AsyncOpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
            response = await client.chat.completions.create(
                model=settings.groq_model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content
        else:
            raise LLMError(f"Unknown AI_PROVIDER '{settings.ai_provider}'")
        return json.loads(text)
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"AI service error ({settings.ai_provider}): {e}") from e
