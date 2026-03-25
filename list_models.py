import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("API KEY NOT FOUND in environment or .env file!")
else:
    print(f"API Key found (length: {len(api_key)})")

genai.configure(api_key=api_key)

print("--- Listing All Available Models ---")
try:
    models = list(genai.list_models())
    if not models:
        print("No models returned.")
    for m in models:
        print(f"Name: {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
