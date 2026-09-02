"""
Quick sanity check: is the Groq API key valid and working?
Run this directly: python test_key.py
"""

import os
from dotenv import load_dotenv
from groq import Groq

# Loads GROQ_API_KEY from your .env file
load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    print("❌ GROQ_API_KEY not found in .env — check your .env file path/name")
    exit(1)

print(f"Found key starting with: {api_key[:8]}...")

client = Groq(api_key=api_key)

try:
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",  # small, fast, cheap model — good for a quick test
        messages=[
            {"role": "user", "content": "Say hello in one short sentence."}
        ],
        max_tokens=20,
    )
    print("✅ Key is working!")
    print("Response:", response.choices[0].message.content)

except Exception as e:
    print("❌ Something went wrong:")
    print(e)