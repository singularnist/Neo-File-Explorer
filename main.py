import os
import json
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Template
from typing import Optional
import platform

app = FastAPI(title="NEO DOCS", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

IGNORE_DIRS = {"__pycache__", ".git", ".venv", ".history", ".idea", "node_modules", ".vscode", "__pycache__", "venv"}
ALLOWED_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yml", ".yaml", ".html", ".css", ".js", ".jsx", ".ts", ".tsx"}

CURRENT_ROOT = os.path.dirname(os.path.abspath(__file__))
USER_ROOT = CURRENT_ROOT

def get_system_roots():
    roots = []
    if platform.system() == 'Windows':
        import string
        for drive in string.ascii_uppercase:
            path = f"{drive}:\\"
            if os.path.exists(path):
                roots.append({
                    "name": f"Drive {drive}:",
                    "path": path,
                    "full_path": path,
                    "type": "root"
                })
    else:
        roots.append({
            "name": "Root (/)",
            "path": "/",
            "full_path": "/",
            "type": "root"
        })
        home = os.path.expanduser("~")
        roots.append({
            "name": "Home",
            "path": home,
            "full_path": home,
            "type": "home"
        })
    return roots

def get_directory_contents(path: str, depth: int = 0, max_depth: int = 2):
    if depth > max_depth:
        return []
    
    dirs = []
    try:
        items = sorted(os.listdir(path))
        for item in items:
            full_path = os.path.join(path, item)
            if os.path.isdir(full_path) and item not in IGNORE_DIRS and not item.startswith('.'):
                dirs.append({
                    "name": item,
                    "path": full_path,
                    "full_path": full_path,
                    "subdirs": get_directory_contents(full_path, depth + 1, max_depth)[:8]
                })
    except (PermissionError, OSError):
        pass
    return dirs[:20]

def build_tree_dict(base_path: str):
    def inner(path):
        d = {}
        try:
            items = sorted(os.listdir(path))
        except (PermissionError, FileNotFoundError):
            return d
            
        for entry in items:
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                if entry not in IGNORE_DIRS and not entry.startswith('.'):
                    d[entry] = inner(full)
            else:
                if any(entry.endswith(ext) for ext in ALLOWED_EXTENSIONS):
                    d[entry] = None
        return d
    
    return inner(base_path)

@app.get("/", response_class=HTMLResponse)
async def index():
    template_path = os.path.join(os.path.dirname(__file__), "index.html")
    
    if not os.path.exists(template_path):
        return HTMLResponse("Template file not found", status_code=500)
    
    try:
        tree_dict = build_tree_dict(USER_ROOT)
        system_roots = get_system_roots()
        
        template = Template(open(template_path, encoding="utf-8").read())
        return template.render(
            tree_json=json.dumps(tree_dict),
            current_root=USER_ROOT,
            system_roots=json.dumps(system_roots),
            default_root=CURRENT_ROOT
        )
    except Exception as e:
        print(f"Error in index: {e}")
        return HTMLResponse(f"Error: {str(e)}", status_code=500)

@app.get("/api/tree")
async def get_tree(root_path: Optional[str] = Query(None, description="Root directory path")):
    global USER_ROOT
    
    if root_path:
        abs_path = os.path.abspath(root_path)
        
        if not os.path.exists(abs_path):
            raise HTTPException(status_code=404, detail=f"Directory not found: {root_path}")
        if not os.path.isdir(abs_path):
            raise HTTPException(status_code=400, detail="Path is not a directory")
        
        USER_ROOT = abs_path
    
    tree_dict = build_tree_dict(USER_ROOT)
    return {
        "tree": tree_dict,
        "current_root": USER_ROOT
    }

@app.get("/api/browse")
async def browse_directory(path: str = Query(..., description="Directory path to browse")):
    abs_path = os.path.abspath(path)
    
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    if not os.path.isdir(abs_path):
        raise HTTPException(status_code=400, detail="Path is not a directory")
    
    try:
        items = []
        for item in sorted(os.listdir(abs_path)):
            full_path = os.path.join(abs_path, item)
            if os.path.isdir(full_path) and item not in IGNORE_DIRS and not item.startswith('.'):
                items.append({
                    "name": item,
                    "path": full_path,
                    "type": "directory"
                })
        
        return {
            "current_path": abs_path,
            "parent": os.path.dirname(abs_path) if abs_path != os.path.dirname(abs_path) else None,
            "items": items
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

@app.get("/api/system-roots")
async def get_system_roots_endpoint():
    return get_system_roots()

@app.get("/file/{file_path:path}")
async def get_file(file_path: str, response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    clean_path = file_path.strip()
    
    if clean_path.startswith('./'):
        clean_path = clean_path[2:]
    
    full_path = os.path.join(USER_ROOT, clean_path)
    full_path = os.path.normpath(full_path)
    
    print(f"DEBUG: USER_ROOT={USER_ROOT}")
    print(f"DEBUG: clean_path={clean_path}")
    print(f"DEBUG: full_path={full_path}")
    
    if not full_path.startswith(USER_ROOT):
        raise HTTPException(status_code=403, detail=f"Access denied - path outside root")
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"File not found: {clean_path}")
    
    if os.path.isdir(full_path):
        raise HTTPException(status_code=400, detail="Cannot view directory")
    
    if not any(full_path.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=403, detail=f"File type not supported. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return PlainTextResponse(content, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    except UnicodeDecodeError:
        try:
            with open(full_path, 'r', encoding='latin-1') as f:
                content = f.read()
            return PlainTextResponse(content, headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            })
        except:
            return PlainTextResponse("Binary file cannot be displayed", status_code=400, headers={
                "Cache-Control": "no-cache, no-store, must-revalidate"
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")