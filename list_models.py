"""Quick script to list all available Gemini models."""
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

print("Available models:\n")
for model in client.models.list():
    print(f"  - {model.name}")
