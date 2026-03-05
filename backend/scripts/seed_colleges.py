import asyncio
import sys
import os
import re
import ast

# Add backend to python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.models.college import CollegeCreate

def parse_js_data(file_path):
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Extract the array content between logic e.g. export const COLLEGE_DATA = [...]
    match = re.search(r'export const COLLEGE_DATA = (\[.*\])', content, re.DOTALL)
    if not match:
        raise ValueError("Could not find COLLEGE_DATA array")
    
    js_array_str = match.group(1)
    
    # Convert JS syntax to Python syntax
    # keys: { id: } -> { "id": } is hard with regex without quoting values.
    # But usually keys are alphanumeric.
    # Replace keys without quotes:  id: -> "id":
    # Be careful not to replace inside strings.
    # Actually, simpler is:
    # 1. comments // ... to top of line
    # 2. true -> True, false -> False, null -> None
    
    # Remove comments
    js_array_str = re.sub(r'//.*', '', js_array_str)
    
    # Replace literals
    js_array_str = js_array_str.replace('true', 'True')
    js_array_str = js_array_str.replace('false', 'False')
    js_array_str = js_array_str.replace('null', 'None')
    
    # It's likely keys are unquoted. Python eval won't like that.
    # 'id': 'scaler' Works. id: 'scaler' Fails.
    # I'll rely on a robust regex to quote keys.
    # Matches word followed by colon, not in quotes.
    # This is fragile but might work for this specific file.
    
    # Alternative: Use simple text processing line by line if structure is consistent.
    # The file looks pretty consistent.
    
    # Let's try quoting keys.
    # We want to match `key:` where key is a valid identifier.
    # But strictly not inside a string.
    # Parsing correctly is hard.
    
    # Fallback: Just manually create a list of dicts for the first few to verify it works, 
    # OR simply don't seed if it's too risky.
    # BUT user wants dynamic backend.
    
    # Better approach: Use node to export JSON.
    pass

async def seed_colleges():
    # Because Parsing JS in Python is flaky, I will trust that the user can import via Admin Panel later.
    # BUT I should try to seed at least one to show it works.
    # Or, I can run a shell command to use node to output json.
    
    # Let's use the node approach inside this script using subprocess
    import subprocess
    import json
    
    cmd = [
        "node", 
        "-e", 
        "import {COLLEGE_DATA} from './src/data/colleges.js'; console.log(JSON.stringify(COLLEGE_DATA));"
    ]
    # This might fail on imports if package.json doesn't say "type": "module".
    # But existing vite app uses modules.
    
    # Let's try running node command directly to get json string.
    try:
        # We need to run this from root where src is.
        project_root = os.path.join(os.path.dirname(__file__), '..', '..')
        result = subprocess.run(
            cmd, 
            cwd=project_root,
            capture_output=True, 
            text=True
        )
        
        if result.returncode != 0:
            # Maybe rename .js to .mjs momentarily?
            # Or assume standard.
            # If it fails, I'll manually seed a few.
            print(f"Node failed: {result.stderr}")
            return

        data = json.loads(result.stdout)
        
        await connect_to_mongo()
        db = get_database()
        
        for item in data:
            # Clean data if needed?
            # Ensure it matches schema.
            try:
                # Remove extra fields if any? CollegeCreate allows extra? Config says yes?
                # Actually Config in CollegeInDB says ignore extra?
                
                # Check exist
                existing = await db.colleges.find_one({"id": item["id"]})
                if existing:
                    print(f"College {item['id']} exists. Skipping.")
                    continue
                
                # Validate with Pydantic
                college_in = CollegeCreate(**item)
                await db.colleges.insert_one(college_in.model_dump(by_alias=True, exclude={"mongo_id"}))
                print(f"Inserted {item['name']}")
                
            except Exception as e:
                print(f"Error inserting {item.get('name')}: {e}")

        await close_mongo_connection()
        
    except Exception as e:
        print(f"Seeding failed: {e}")

if __name__ == "__main__":
    asyncio.run(seed_colleges())
