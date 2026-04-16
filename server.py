from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
import uvicorn
import threading
from fastmcp import FastMCP
import httpx
import os
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Codever")

BASE_URL = "https://www.codever.dev/api"
BEARER_TOKEN = os.environ.get("CODEVER_BEARER_TOKEN", "")


def get_headers():
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@mcp.tool()
async def search_bookmarks(
    query: Optional[str] = None,
    tags: Optional[List[str]] = None,
    public: bool = True,
    limit: int = 10,
    page: int = 1,
) -> dict:
    """Search public or personal bookmarks by query text, tags, or both."""
    params = {
        "limit": limit,
        "page": page,
    }
    if query:
        params["q"] = query
    if tags:
        params["tags"] = ",".join(tags)

    if public:
        url = f"{BASE_URL}/public/bookmarks"
    else:
        url = f"{BASE_URL}/personal/users/bookmarks"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=get_headers(), params=params)
        if response.status_code == 200:
            return {"success": True, "data": response.json(), "status_code": response.status_code}
        else:
            return {"success": False, "error": response.text, "status_code": response.status_code}


@mcp.tool()
async def create_bookmark(
    url: str,
    title: str,
    tags: List[str],
    user_id: str,
    description: Optional[str] = None,
    public: bool = False,
) -> dict:
    """Save a new bookmark to Codever for the authenticated user."""
    payload = {
        "location": url,
        "name": title,
        "tags": tags,
        "public": public,
        "userId": user_id,
    }
    if description is not None:
        payload["description"] = description

    endpoint = f"{BASE_URL}/personal/users/{user_id}/bookmarks"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=get_headers(), json=payload)
        if response.status_code in (200, 201):
            return {"success": True, "data": response.json() if response.text else {}, "status_code": response.status_code}
        else:
            return {"success": False, "error": response.text, "status_code": response.status_code}


@mcp.tool()
async def update_bookmark(
    bookmark_id: str,
    user_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    public: Optional[bool] = None,
) -> dict:
    """Update an existing bookmark's metadata such as title, description, tags, or public visibility."""
    # First retrieve the existing bookmark
    endpoint = f"{BASE_URL}/personal/users/{user_id}/bookmarks/{bookmark_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        get_response = await client.get(endpoint, headers=get_headers())
        if get_response.status_code != 200:
            return {"success": False, "error": f"Could not retrieve bookmark: {get_response.text}", "status_code": get_response.status_code}

        bookmark = get_response.json()

        # Apply updates
        if title is not None:
            bookmark["name"] = title
        if description is not None:
            bookmark["description"] = description
        if tags is not None:
            bookmark["tags"] = tags
        if public is not None:
            bookmark["public"] = public

        put_response = await client.put(endpoint, headers=get_headers(), json=bookmark)
        if put_response.status_code in (200, 204):
            return {"success": True, "data": put_response.json() if put_response.text else {}, "status_code": put_response.status_code}
        else:
            return {"success": False, "error": put_response.text, "status_code": put_response.status_code}


@mcp.tool()
async def delete_bookmark(
    bookmark_id: str,
    user_id: str,
) -> dict:
    """Permanently delete a bookmark by its ID for the authenticated user."""
    endpoint = f"{BASE_URL}/personal/users/{user_id}/bookmarks/{bookmark_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(endpoint, headers=get_headers())
        if response.status_code in (200, 204):
            return {"success": True, "message": "Bookmark deleted successfully", "status_code": response.status_code}
        else:
            return {"success": False, "error": response.text, "status_code": response.status_code}


@mcp.tool()
async def manage_snippet(
    action: str,
    user_id: str,
    title: str,
    code: str,
    language: str,
    tags: List[str],
    description: Optional[str] = None,
    public: bool = False,
    snippet_id: Optional[str] = None,
) -> dict:
    """Create or update a code snippet in Codever."""
    payload = {
        "title": title,
        "codeSnippets": [
            {
                "code": code,
                "language": language,
            }
        ],
        "tags": tags,
        "public": public,
        "userId": user_id,
    }
    if description is not None:
        payload["description"] = description

    base_snippets_url = f"{BASE_URL}/personal/users/{user_id}/snippets"

    async with httpx.AsyncClient(timeout=30.0) as client:
        if action == "create":
            response = await client.post(base_snippets_url, headers=get_headers(), json=payload)
            if response.status_code in (200, 201):
                return {"success": True, "data": response.json() if response.text else {}, "status_code": response.status_code}
            else:
                return {"success": False, "error": response.text, "status_code": response.status_code}

        elif action == "update":
            if not snippet_id:
                return {"success": False, "error": "snippet_id is required for update action"}

            endpoint = f"{base_snippets_url}/{snippet_id}"
            # Retrieve existing snippet first
            get_response = await client.get(endpoint, headers=get_headers())
            if get_response.status_code == 200:
                existing = get_response.json()
                existing.update(payload)
                payload_to_send = existing
            else:
                payload_to_send = payload

            payload_to_send["_id"] = snippet_id
            put_response = await client.put(endpoint, headers=get_headers(), json=payload_to_send)
            if put_response.status_code in (200, 204):
                return {"success": True, "data": put_response.json() if put_response.text else {}, "status_code": put_response.status_code}
            else:
                return {"success": False, "error": put_response.text, "status_code": put_response.status_code}
        else:
            return {"success": False, "error": f"Unknown action '{action}'. Must be 'create' or 'update'."}


@mcp.tool()
async def get_user_profile(
    user_id: str,
) -> dict:
    """Retrieve a user's profile including their pinned bookmarks, watched tags, favorite bookmarks, and account settings."""
    endpoint = f"{BASE_URL}/personal/users/{user_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(endpoint, headers=get_headers())
        if response.status_code == 200:
            return {"success": True, "data": response.json(), "status_code": response.status_code}
        else:
            return {"success": False, "error": response.text, "status_code": response.status_code}


@mcp.tool()
async def manage_user_tags(
    user_id: str,
    action: str,
    tags: List[str],
) -> dict:
    """Add or remove watched tags from a user's profile."""
    # First, retrieve the current user profile to get existing watched tags
    profile_endpoint = f"{BASE_URL}/personal/users/{user_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        get_response = await client.get(profile_endpoint, headers=get_headers())
        if get_response.status_code != 200:
            return {"success": False, "error": f"Could not retrieve user profile: {get_response.text}", "status_code": get_response.status_code}

        profile = get_response.json()
        current_tags = profile.get("watchedTags", [])

        if action == "add":
            updated_tags = list(set(current_tags + tags))
        elif action == "remove":
            updated_tags = [t for t in current_tags if t not in tags]
        else:
            return {"success": False, "error": f"Unknown action '{action}'. Must be 'add' or 'remove'."}

        profile["watchedTags"] = updated_tags

        put_response = await client.put(profile_endpoint, headers=get_headers(), json=profile)
        if put_response.status_code in (200, 204):
            return {
                "success": True,
                "message": f"Tags {action}ed successfully",
                "watchedTags": updated_tags,
                "status_code": put_response.status_code,
            }
        else:
            return {"success": False, "error": put_response.text, "status_code": put_response.status_code}


@mcp.tool()
async def like_bookmark(
    bookmark_id: str,
    user_id: str,
    action: str,
) -> dict:
    """Like or unlike a public bookmark on behalf of the authenticated user."""
    if action == "like":
        endpoint = f"{BASE_URL}/personal/users/{user_id}/likes/bookmarks/{bookmark_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, headers=get_headers(), json={})
            if response.status_code in (200, 201, 204):
                return {"success": True, "message": "Bookmark liked successfully", "status_code": response.status_code}
            else:
                return {"success": False, "error": response.text, "status_code": response.status_code}
    elif action == "unlike":
        endpoint = f"{BASE_URL}/personal/users/{user_id}/likes/bookmarks/{bookmark_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(endpoint, headers=get_headers())
            if response.status_code in (200, 204):
                return {"success": True, "message": "Bookmark unliked successfully", "status_code": response.status_code}
            else:
                return {"success": False, "error": response.text, "status_code": response.status_code}
    else:
        return {"success": False, "error": f"Unknown action '{action}'. Must be 'like' or 'unlike'."}




_SERVER_SLUG = "codeverdotdev-codever"

def _track(tool_name: str, ua: str = ""):
    try:
        import urllib.request, json as _json
        data = _json.dumps({"slug": _SERVER_SLUG, "event": "tool_call", "tool": tool_name, "user_agent": ua}).encode()
        req = urllib.request.Request("https://www.volspan.dev/api/analytics/event", data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

async def health(request):
    return JSONResponse({"status": "ok", "server": mcp.name})

async def tools(request):
    registered = await mcp.list_tools()
    tool_list = [{"name": t.name, "description": t.description or ""} for t in registered]
    return JSONResponse({"tools": tool_list, "count": len(tool_list)})

mcp_app = mcp.http_app(transport="streamable-http", stateless_http=True)

class _FixAcceptHeader:
    """Ensure Accept header includes both types FastMCP requires."""
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            accept = headers.get(b"accept", b"").decode()
            if "text/event-stream" not in accept:
                new_headers = [(k, v) for k, v in scope["headers"] if k != b"accept"]
                new_headers.append((b"accept", b"application/json, text/event-stream"))
                scope = dict(scope, headers=new_headers)
        await self.app(scope, receive, send)

app = _FixAcceptHeader(Starlette(
    routes=[
        Route("/health", health),
        Route("/tools", tools),
        Mount("/", mcp_app),
    ],
    lifespan=mcp_app.lifespan,
))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
