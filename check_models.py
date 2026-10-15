import os

from dotenv import load_dotenv
from groq import Groq

from src.nlp.model_manager import ModelManager

load_dotenv(override=True)
mm = ModelManager(Groq(api_key=os.environ["GROQ_API_KEY"]))
print("list fetched:", mm.refresh())
print("smart ->", mm.candidates("smart")[:3])
print("fast  ->", mm.candidates("fast")[:3])