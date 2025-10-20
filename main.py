from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Optional, List
import hashlib
import re
from datetime import datetime
import json
import os
from urllib.parse import unquote_plus

app = FastAPI(title="String Analysis API")

# ----- Pydantic models -----
class CreateRequest(BaseModel):
    value: str

class Properties(BaseModel):
    length: int
    is_palindrome: bool
    unique_characters: int
    word_count: int
    sha256_hash: str
    character_frequency_map: Dict[str, int]

class StoredString(BaseModel):
    id: str
    value: str
    properties: Properties
    created_at: str

# ----- In-memory DB + persistence -----
string_db: Dict[str, StoredString] = {}
DB_FILE = "string_db.json"

def save_db() -> None:
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            # store Pydantic dicts
            json.dump({k: v.dict() for k, v in string_db.items()}, f, indent=2, ensure_ascii=False)
    except Exception:
        # avoid crashing on save failure; log in real app
        pass

def load_db() -> None:
    if not os.path.exists(DB_FILE):
        return
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in data.items():
                string_db[k] = StoredString(**v)
    except Exception:
        # ignore malformed DB for now
        pass

@app.on_event("startup")
def on_startup():
    load_db()

@app.on_event("shutdown")
def on_shutdown():
    save_db()

# ----- Utilities -----
def generate_sha_256(data: str) -> str:
    sha_256 = hashlib.sha256()
    sha_256.update(data.encode("utf-8"))
    return sha_256.hexdigest()

def clean_for_char_ops(data: str) -> str:
    # remove non-word chars and underscores, make lowercase
    return re.sub(r'[\W_]+', '', data.lower())

def palindrome(data: str) -> bool:
    clean_data = clean_for_char_ops(data)
    return clean_data == clean_data[::-1]

def char_count(data: str) -> Dict[str, int]:
    chars: Dict[str, int] = {}
    clean_data = clean_for_char_ops(data)
    for ch in clean_data:
        chars[ch] = chars.get(ch, 0) + 1
    return chars

def unique_characters_count(data: str) -> int:
    # distinct characters (case-insensitive; non-word filtered)
    return len(char_count(data).keys())

def word_count(data: str) -> int:
    # words separated by whitespace
    if not data or not data.strip():
        return 0
    return len(data.split())

# ----- Endpoints -----

@app.get("/", summary="API root")
def root():
    return {
        "message": "String Analysis API",
        "endpoints": ["/strings (POST, GET)", "/strings/{id_or_value} (GET, DELETE)", "/strings/filter-by-natural-language"]
    }

@app.post("/strings", response_model=StoredString, status_code=201)
async def create_string(req: CreateRequest):
    if req.value is None:
        raise HTTPException(status_code=400, detail="Missing 'value' field")
    if not isinstance(req.value, str):
        raise HTTPException(status_code=422, detail="'value' must be a string")

    value = req.value
    # check duplicates by exact string match
    if any(stored.value == value for stored in string_db.values()):
        raise HTTPException(status_code=409, detail="String already exists in the system")

    sha = generate_sha_256(value)
    props = Properties(
        length=len(value),
        is_palindrome=palindrome(value),
        unique_characters=unique_characters_count(value),
        word_count=word_count(value),
        sha256_hash=sha,
        character_frequency_map=char_count(value),
    )
    created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    stored = StoredString(id=sha, value=value, properties=props, created_at=created_at)
    string_db[sha] = stored

    # persist
    save_db()

    return stored

@app.get("/strings/{id_or_value}", response_model=StoredString, status_code=200)
async def get_string(id_or_value: str):
    # decode in case user provided URL-encoded value
    identifier = unquote_plus(id_or_value)

    # 1. try treat as SHA key
    if identifier in string_db:
        return string_db[identifier]

    # 2. try find by exact value
    for st in string_db.values():
        if st.value == identifier:
            return st

    raise HTTPException(status_code=404, detail="String not found")

@app.delete("/strings/{id_or_value}", status_code=204)
async def delete_string(id_or_value: str):
    identifier = unquote_plus(id_or_value)

    # delete by SHA
    if identifier in string_db:
        del string_db[identifier]
        save_db()
        return None

    # delete by value (first match)
    found_key = None
    for k, v in string_db.items():
        if v.value == identifier:
            found_key = k
            break
    if found_key:
        del string_db[found_key]
        save_db()
        return None

    raise HTTPException(status_code=404, detail="String not found")

@app.get("/strings", status_code=200)
async def list_strings(
    is_palindrome: Optional[bool] = Query(None),
    min_length: Optional[int] = Query(None, ge=0),
    max_length: Optional[int] = Query(None, ge=0),
    word_count: Optional[int] = Query(None, ge=0),
    contains_character: Optional[str] = Query(None, min_length=1, max_length=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
):
    # validations
    if min_length is not None and max_length is not None and min_length > max_length:
        raise HTTPException(status_code=400, detail="min_length cannot be greater than max_length")
    if contains_character is not None and len(contains_character) != 1:
        raise HTTPException(status_code=400, detail="contains_character must be a single character")

    applied_filters = {
        "is_palindrome": is_palindrome,
        "min_length": min_length,
        "max_length": max_length,
        "word_count": word_count,
        "contains_character": contains_character,
    }

    def matches(st: StoredString) -> bool:
        p = st.properties
        if is_palindrome is not None and p.is_palindrome != is_palindrome:
            return False
        if min_length is not None and p.length < min_length:
            return False
        if max_length is not None and p.length > max_length:
            return False
        if word_count is not None and p.word_count != word_count:
            return False
        if contains_character is not None:
            if contains_character.lower() not in p.character_frequency_map:
                return False
        return True

    all_results = [s for s in string_db.values() if matches(s)]
    paginated = all_results[skip: skip + limit]

    return {
        "data": [s.dict() for s in paginated],
        "count": len(all_results),
        "returned": len(paginated),
        "filters_applied": applied_filters,
    }

@app.get("/strings/filter-by-natural-language", status_code=200)
async def filter_by_natural_language(query: str = Query(..., min_length=1)):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query parameter required")

    q = query.lower()
    parsed = {"original": query, "parsed_filters": {}}

    # heuristics
    if "single word" in q or "single-word" in q:
        parsed["parsed_filters"]["word_count"] = 1
    if "more than one word" in q or "multiple words" in q:
        parsed["parsed_filters"]["min_word_count"] = 2
    if "palindrom" in q:  # catches palindromic / palindrome
        parsed["parsed_filters"]["is_palindrome"] = True

    m = re.search(r"longer than (\d+)", q)
    if m:
        parsed["parsed_filters"]["min_length"] = int(m.group(1)) + 1

    m2 = re.search(r"contain(?:s|ing)?(?: the letter)?\s+([a-zA-Z])", q)
    if m2:
        parsed["parsed_filters"]["contains_character"] = m2.group(1).lower()

    if "first vowel" in q:
        # heuristic: first vowel = 'a'
        parsed["parsed_filters"]["contains_character"] = parsed["parsed_filters"].get("contains_character", "a")

    if not parsed["parsed_filters"]:
        raise HTTPException(status_code=400, detail="Unable to parse natural language query")

    pf = parsed["parsed_filters"]
    if "min_length" in pf and "max_length" in pf and pf["min_length"] > pf["max_length"]:
        raise HTTPException(status_code=422, detail="Parsed filters conflict (min_length > max_length)")

    def matches_parsed(st: StoredString) -> bool:
        p = st.properties
        if "is_palindrome" in pf and p.is_palindrome != pf["is_palindrome"]:
            return False
        if "min_length" in pf and p.length < pf["min_length"]:
            return False
        if "max_length" in pf and p.length > pf["max_length"]:
            return False
        if "word_count" in pf and p.word_count != pf["word_count"]:
            return False
        if "contains_character" in pf:
            if pf["contains_character"].lower() not in p.character_frequency_map:
                return False
        return True

    results = [s for s in string_db.values() if matches_parsed(s)]

    return {
        "data": [s.dict() for s in results],
        "count": len(results),
        "interpreted_query": parsed,
    }
