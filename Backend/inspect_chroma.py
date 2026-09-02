# inspect_chroma.py
import chromadb

chroma_client = chromadb.PersistentClient(path="./chroma_data")
collection = chroma_client.get_or_create_collection(name="resume_embeddings")

print("Total resumes stored:", collection.count())

result = collection.get(ids=["14"])
print(result["documents"][0])