from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
from typing import Dict, Optional,List
import hashlib, re
from datetime import datetime


app=FastAPI()


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

string_db: Dict[str,StoredString]={}

def generate_sha_256(data:str)-> str:
    """Generate the sha_256 for a given string"""
    sha_256= hashlib.sha256()
    # update the sha_256 with the data passed
    sha_256.update(data.encode('utf-8'))

    return sha_256.hexdigest()


def palindrome(data:str)-> str:
    """check if a given string is palindrome"""
    clean_data= re.sub(r'[^a-z0-9]', '', data.lower())
    return clean_data== clean_data[::-1]



def char_count(data:str)-> dict[str:int]:
    """Count occurence of charaters in a string  and returns  string"""
    chars={}
    clean_data= re.sub(r'[^a-z0-9]', '', data.lower())
    for char in clean_data:
        chars[char]=chars.get(char,0)+1
    return chars

def unique_char(data:str)-> int:
    """Find the character that does not occur more than once"""
    chars=char_count(data)
    unique_count = len([char for char, count in chars.items() if count == 1])
    return unique_count

def word_count(data:str)->int:
    """counts number of words in the input"""
    words= re.findall(r'\b\w+\b',data)
    return len(words)

@app.get("/")
def root():
    return {"message": "Hello, world!"}

@app.post("/strings/", response_model=StoredString, status_code=201)
async def create_string(req: CreateRequest):
    try:
        if not req.value:
            raise HTTPException(status_code=400,detail="Missing 'value' field")
        value = req.value
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"Invalid data type for {value}, must be a string")
        if value in string_db:
            raise HTTPException(status_code=409, detail="String already exists in the system")
        sha = generate_sha_256(value)
        props = Properties(
            length=len(value),
            is_palindrome=palindrome(value),
            unique_characters=unique_char(value),
            word_count=word_count(value),
            sha256_hash=sha,
            character_frequency_map=char_count(value)
        )
        stored = StoredString(
            id=sha,
            value=value,
            properties=props,
            created_at=datetime.utcnow().isoformat() + "Z"
        )
        string_db[sha] = stored
        return  stored
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/strings/{hash_id}", response_model= StoredString, status_code=200)
async def get_string(hash_id:str):
    if hash_id not in string_db:
        raise HTTPException(status_code=404, detail="String  not found")
    return string_db[hash_id]


@app.get("/strings")
async def list_strings(
    is_palindrome: Optional[bool]=None,
    min_length: Optional[int]=None,
    max_length: Optional[int]=None,
    word_count_param:Optional[int]=None,
    contains_character:Optional[str]=None
):
    # basic validation
    if contains_character is not None and len(contains_character) != 1:
        raise HTTPException(status_code=400, detail="contains_character must be a single character")
    if min_length is not None and max_length is not None and min_length > max_length:
        raise HTTPException(status_code=400, detail="min_length cannot be greater than max_length")

    applied_filters = {
        "is_palindrome": is_palindrome,
        "min_length": min_length,
        "max_length": max_length,
        "word_count": word_count_param,
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
        if word_count_param is not None and p.word_count != word_count_param:
            return False
        if contains_character is not None:
            # check against cleaned character_frequency_map keys
            if contains_character.lower() not in p.character_frequency_map:
                return False
        return True

    results = [s for s in string_db.values() if matches(s)]
    return {
        "data": [s.dict() for s in results],
        "count": len(results),
        "filters_applied": applied_filters,
    }
    


# Natural language filtering (simple heuristics)
@app.get("/strings/filter-by-natural-language")
async def filter_by_natural_language(query: str):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query parameter required")

    q = query.lower()
    parsed = {"original": query, "parsed_filters": {}}

    # heuristics
    if "single word" in q or "single-word" in q:
        parsed["parsed_filters"]["word_count"] = 1
    if "palindrom" in q:  # catches palindromic / palindrome
        parsed["parsed_filters"]["is_palindrome"] = True

    m = re.search(r"longer than (\d+)", q)
    if m:
        parsed["parsed_filters"]["min_length"] = int(m.group(1)) + 1

    m2 = re.search(r"contain(?:s|ing)?(?: the letter)?\s+([a-z])", q)
    if m2:
        parsed["parsed_filters"]["contains_character"] = m2.group(1)

    if "first vowel" in q:
        # heuristic: first vowel = 'a'
        parsed["parsed_filters"]["contains_character"] = parsed["parsed_filters"].get("contains_character", "a")

    if not parsed["parsed_filters"]:
        raise HTTPException(status_code=400, detail="Unable to parse natural language query")

    # check for simple conflicts
    pf = parsed["parsed_filters"]
    if "min_length" in pf and "max_length" in pf and pf["min_length"] > pf["max_length"]:
        raise HTTPException(status_code=422, detail="Parsed filters conflict (min_length > max_length)")

    # reuse filtering logic
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




@app.delete("/strings/{hash_id}", status_code=204)
async def delete_string(hash_id: str):
    if hash_id not in string_db:
        raise HTTPException(status_code=404, detail="String not found")
    del string_db[hash_id]
    return None
