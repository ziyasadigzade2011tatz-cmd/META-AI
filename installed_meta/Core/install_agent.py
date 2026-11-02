from pathlib import Path

path = Path(r"D:\META\Core\main.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_AGENT_RUNTIME_V1"

if marker in code:
    print("Agent Runtime already installed")
else:
    backup = path.with_name("main_before_agent.py")
    backup.write_text(code, encoding="utf-8")

    code += '''

# META_AGENT_RUNTIME_V1

from agent_tools import list_files, read_file, create_file
from pydantic import BaseModel as AgentBaseModel


class CreateFileRequest(AgentBaseModel):
    path: str
    content: str


@app.get("/agent/files")
async def agent_files(folder: str = "."):
    try:
        return {"files": list_files(folder)}
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/agent/read")
async def agent_read(path: str):
    try:
        return {"path": path, "content": read_file(path)}
    except (ValueError, OSError, UnicodeError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/agent/create")
async def agent_create(request: CreateFileRequest):
    try:
        return create_file(request.path, request.content)
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail="File already exists"
        )
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error))
'''

    path.write_text(code, encoding="utf-8")
    print("META Agent Runtime 1.0 connected")
