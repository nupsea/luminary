import json
import random
import os
from pathlib import Path

# Provide random contexts to LLM to generate Q&A
prompt_template = """
You are a teacher creating a reading comprehension test for a book.
Given the following excerpt from "Alice in Wonderland", please generate ONE question, the correct answer, and an exact substring from the excerpt that acts as a context hint.
The context_hint MUST be an exact verbatim substring from the excerpt that contains the answer. It should be 5-15 words long.

Excerpt:
{excerpt}

Output your response strictly in the following JSON format:
{{
  "question": "The question here",
  "ground_truth_answer": "The answer here",
  "context_hint": "exact verbatim substring from excerpt"
}}
"""

def generate_dataset():
    book_path = Path("DATA/books/alice_in_wonderland.txt")
    if not book_path.exists():
        print("Book not found")
        return

    text = book_path.read_text(encoding="utf-8")
    # Very naive chunking by paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 200]
    
    # Select 20 random paragraphs
    selected_paragraphs = random.sample(paragraphs, min(20, len(paragraphs)))
    
    import litellm
    litellm.set_verbose=False

    dataset = []
    
    for i, p in enumerate(selected_paragraphs):
        print(f"Generating for chunk {i+1}/20...")
        try:
            resp = litellm.completion(
                model="ollama/mistral", # Assuming mistral is available locally
                messages=[{"role": "user", "content": prompt_template.format(excerpt=p)}],
                response_format={ "type": "json_object" }
            )
            content = resp.choices[0].message.content
            parsed = json.loads(content)
            
            # verify context_hint is in paragraph
            hint_norm = " ".join(parsed["context_hint"].split())
            p_norm = " ".join(p.split())
            if hint_norm.lower() not in p_norm.lower():
                print("Hint not in text exactly, skipping.")
                continue

            parsed["document_id"] = "TBD"
            parsed["source_file"] = "DATA/books/alice_in_wonderland.txt"
            dataset.append(parsed)
        except Exception as e:
            print("Error generating:", e)

    out_path = Path("evals/golden/alice_in_wonderland.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item) + "\n")
            
    print(f"Saved {len(dataset)} items to {out_path}")

if __name__ == "__main__":
    generate_dataset()
