...existing code...

# String Serializer (FastAPI)

Small FastAPI service that accepts a string, analyzes it (length, palindrome, unique characters, word count, sha256, character frequency) and stores the result in an in-memory database keyed by the SHA-256 hash.

## Requirements
- Python 3.9+
- Dependencies:
  - fastapi
  - uvicorn
  - pydantic

Install:
```bash
python -m pip install fastapi uvicorn
```

## Run (Windows)
From project folder (where `main.py` lives):
```powershell
uvicorn main:app --reload
```
Server URL: http://127.0.0.1:8000

## Data model (response JSON)
Each stored entry looks like:
```json
{
  "id": "sha256_hash_value",
  "value": "string to analyze",
  "properties": {
    "length": 16,
    "is_palindrome": false,
    "unique_characters": 12,
    "word_count": 3,
    "sha256_hash": "abc123...",
    "character_frequency_map": { "s": 2, "t": 3, "r": 2 }
  },
  "created_at": "2025-08-27T10:00:00Z"
}
```

## Endpoints

- POST /strings/
  - Request JSON: `{ "value": "string to analyze" }`
  - Response: Stored object (see model above).
  - Example:
    ```bash
    curl -X POST "http://127.0.0.1:8000/strings/" -H "Content-Type: application/json" -d "{\"value\":\"string to analyze\"}"
    ```

- GET /strings/{hash_id}
  - Return single stored item by SHA-256 id.
  - Example:
    ```
    http://127.0.0.1:8000/strings/{hash_id}
    ```

- GET /strings
  - List all stored items. Supports query filters:
    - is_palindrome: true|false
    - min_length: integer
    - max_length: integer
    - word_count: integer
    - contains_character: single character (a-z)
  - Example:
    ```
    GET /strings?is_palindrome=true&min_length=5&max_length=20&word_count=2&contains_character=a
    ```

  - Response shape:
    ```json
    {
      "data": [ /* array of StoredString */ ],
      "count": 15,
      "filters_applied": { /* values */ }
    }
    ```

- GET /strings/filter-by-natural-language?query=...
  - Provide a plain-English query and the server attempts to convert it into filters (heuristic parsing).
  - Example queries:
    - `all single word palindromic strings` → word_count=1, is_palindrome=true
    - `strings longer than 10 characters` → min_length=11
    - `strings containing the letter z` → contains_character=z
  - Response includes `interpreted_query` with parsed filters.

- DELETE /strings/{hash_id}
  - Remove stored entry by id.

## Notes & Limitations
- DB is in-memory and lost on server restart.
- Natural-language filtering is heuristic/regex-based — not a full NLP parser. Expect imperfect parsing for complex phrasing.
- `contains_character` expects a single character; invalid values return 400.
- Duplicate POST of the same string will overwrite the entry for the same hash.

## Testing
Use the interactive docs:
- Open http://127.0.0.1:8000/docs

If you want more parsing rules for the natural-language endpoint or a requirements.txt created, say which parser/library you prefer and it will be added.