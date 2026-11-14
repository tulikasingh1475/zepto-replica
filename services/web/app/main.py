"""Demo web UI. Serves the page and forwards /api/<port>/<path> to the local services.
The proxy exists only so the browser needs no CORS setup. Ours."""
import pathlib

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

app = FastAPI(title="web-demo")
STATIC = pathlib.Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.api_route("/api/{port}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(port: int, path: str, request: Request):
    if not 8000 <= port <= 8009:
        raise HTTPException(404, "unknown service")
    async with httpx.AsyncClient(timeout=10) as c:
        try:
            r = await c.request(request.method, f"http://127.0.0.1:{port}/{path}",
                                params=request.query_params, content=await request.body(),
                                headers={"content-type": "application/json"})
        except httpx.HTTPError:
            raise HTTPException(502, "service unreachable")
    return Response(r.content, status_code=r.status_code, media_type="application/json")
