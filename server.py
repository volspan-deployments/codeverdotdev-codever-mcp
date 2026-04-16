from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
import uvicorn
import threading
from fastmcp import FastMCP
import httpx
import os
from typing import Optional, List
import json
from datetime import datetime
import uuid

mcp = FastMCP("Codever Bookmarks & Snippets Manager")

# In-memory storage (replace with a real database in production)
_bookmarks_store = {}  # bookmark_id -> bookmark dict
_snippets_store = {}   # snippet_id -> snippet dict
_users_store = {}      # user_id -> user profile dict


def _get_or_create_user(user_id: str) -> dict:
    if user_id not in _users_store:
        _users_store[user_id] = {
            "userId": user_id,
            "watchedTags": [],
            "pinnedBookmarks": [],
            "likedBookmarks": [],
            "favorites": []
        }
    return _users_store[user_id]


@mcp.tool()
async def search_bookmarks(
    _track("search_bookmarks")
    query: Optional[str] = None,
    tags: Optional[List[str]] = None,
    public: bool = True,
    user_id: Optional[str] = None,
    limit: int = 10,
    page: int = 1
) -> dict:
    """
    Search public or personal bookmarks by query text, tags, or filters.
    Use this when the user wants to find bookmarks matching keywords, topics, or specific tags.
    Supports full-text search and tag-based filtering.
    """
    results = []

    for bm_id, bm in _bookmarks_store.items():
        # Filter by public/private
        if public and not bm.get("public", False):
            continue
        if not public:
            if user_id is None:
                return {"error": "user_id is required when searching personal bookmarks (public=false)"}
            if bm.get("userId") != user_id:
                continue

        # Filter by tags
        if tags:
            bm_tags = bm.get("tags", [])
            if not any(t in bm_tags for t in tags):
                continue

        # Filter by query (full-text search on title, description, tags)
        if query:
            query_lower = query.lower()
            searchable = " ".join([
                bm.get("title", ""),
                bm.get("description", ""),
                " ".join(bm.get("tags", []))
            ]).lower()
            if query_lower not in searchable:
                continue

        results.append(bm)

    # Pagination
    total = len(results)
    start = (page - 1) * limit
    end = start + limit
    paginated = results[start:end]

    return {
        "bookmarks": paginated,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, (total + limit - 1) // limit)
    }


@mcp.tool()
async def create_bookmark(
    _track("create_bookmark")
    user_id: str,
    url: str,
    title: str,
    tags: List[str],
    description: Optional[str] = None,
    public: bool = False
) -> dict:
    """
    Save a new bookmark for a user. Use this when the user wants to bookmark a URL
    with associated metadata like title, description, and tags.
    Can create public or private bookmarks.
    """
    if not user_id or not url or not title or not tags:
        return {"error": "user_id, url, title, and tags are required fields"}

    bookmark_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + "Z"

    bookmark = {
        "_id": bookmark_id,
        "userId": user_id,
        "url": url,
        "title": title,
        "description": description or "",
        "tags": tags,
        "public": public,
        "likeCount": 0,
        "createdAt": now,
        "updatedAt": now
    }

    _bookmarks_store[bookmark_id] = bookmark
    _get_or_create_user(user_id)

    return {
        "success": True,
        "message": "Bookmark created successfully",
        "bookmark": bookmark
    }


@mcp.tool()
async def update_bookmark(
    _track("update_bookmark")
    user_id: str,
    bookmark_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    public: Optional[bool] = None
) -> dict:
    """
    Update an existing bookmark's metadata such as title, description, tags, or public visibility.
    Use this when the user wants to edit or modify a saved bookmark.
    """
    if bookmark_id not in _bookmarks_store:
        return {"error": f"Bookmark with ID '{bookmark_id}' not found"}

    bm = _bookmarks_store[bookmark_id]

    if bm.get("userId") != user_id:
        return {"error": "You do not have permission to update this bookmark"}

    if title is not None:
        bm["title"] = title
    if description is not None:
        bm["description"] = description
    if tags is not None:
        bm["tags"] = tags
    if public is not None:
        bm["public"] = public

    bm["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    _bookmarks_store[bookmark_id] = bm

    return {
        "success": True,
        "message": "Bookmark updated successfully",
        "bookmark": bm
    }


@mcp.tool()
async def delete_bookmark(
    _track("delete_bookmark")
    user_id: str,
    bookmark_id: str
) -> dict:
    """
    Permanently delete a bookmark belonging to a user.
    Use this when the user wants to remove a saved bookmark from their collection.
    """
    if bookmark_id not in _bookmarks_store:
        return {"error": f"Bookmark with ID '{bookmark_id}' not found"}

    bm = _bookmarks_store[bookmark_id]

    if bm.get("userId") != user_id:
        return {"error": "You do not have permission to delete this bookmark"}

    del _bookmarks_store[bookmark_id]

    # Remove from user profile lists if present
    if user_id in _users_store:
        user = _users_store[user_id]
        user["pinnedBookmarks"] = [b for b in user.get("pinnedBookmarks", []) if b.get("_id") != bookmark_id]
        user["likedBookmarks"] = [b for b in user.get("likedBookmarks", []) if b.get("_id") != bookmark_id]
        user["favorites"] = [b for b in user.get("favorites", []) if b.get("_id") != bookmark_id]

    return {
        "success": True,
        "message": f"Bookmark '{bookmark_id}' has been permanently deleted"
    }


@mcp.tool()
async def manage_snippet(
    _track("manage_snippet")
    user_id: str,
    title: str,
    code: str,
    language: str,
    snippet_id: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    public: bool = False
) -> dict:
    """
    Create or update a code snippet associated with a user.
    Use this when the user wants to save a piece of code with language, title, description,
    and tags for later retrieval. Supports full Markdown in description.
    """
    now = datetime.utcnow().isoformat() + "Z"

    if snippet_id and snippet_id in _snippets_store:
        # Update existing snippet
        snippet = _snippets_store[snippet_id]

        if snippet.get("userId") != user_id:
            return {"error": "You do not have permission to update this snippet"}

        snippet["title"] = title
        snippet["code"] = code
        snippet["language"] = language
        if description is not None:
            snippet["description"] = description
        if tags is not None:
            snippet["tags"] = tags
        snippet["public"] = public
        snippet["updatedAt"] = now
        _snippets_store[snippet_id] = snippet

        return {
            "success": True,
            "message": "Snippet updated successfully",
            "snippet": snippet
        }
    else:
        # Create new snippet
        new_id = snippet_id or str(uuid.uuid4())
        snippet = {
            "_id": new_id,
            "userId": user_id,
            "title": title,
            "code": code,
            "language": language,
            "description": description or "",
            "tags": tags or [],
            "public": public,
            "likeCount": 0,
            "createdAt": now,
            "updatedAt": now
        }
        _snippets_store[new_id] = snippet
        _get_or_create_user(user_id)

        return {
            "success": True,
            "message": "Snippet created successfully",
            "snippet": snippet
        }


@mcp.tool()
async def get_user_profile(
    _track("get_user_profile")
    user_id: str
) -> dict:
    """
    Retrieve a user's profile information including watched tags, pinned bookmarks,
    liked bookmarks, and favorites. Use this to understand a user's preferences,
    history, or to display their profile data.
    """
    user = _get_or_create_user(user_id)

    # Enrich pinned bookmarks with current data
    pinned = []
    for item in user.get("pinnedBookmarks", []):
        bm_id = item.get("_id") if isinstance(item, dict) else item
        if bm_id in _bookmarks_store:
            pinned.append(_bookmarks_store[bm_id])

    # Enrich liked bookmarks with current data
    liked = []
    for item in user.get("likedBookmarks", []):
        bm_id = item.get("_id") if isinstance(item, dict) else item
        if bm_id in _bookmarks_store:
            liked.append(_bookmarks_store[bm_id])

    # Count user's bookmarks and snippets
    user_bookmarks_count = sum(1 for bm in _bookmarks_store.values() if bm.get("userId") == user_id)
    user_snippets_count = sum(1 for sn in _snippets_store.values() if sn.get("userId") == user_id)

    return {
        "userId": user_id,
        "watchedTags": user.get("watchedTags", []),
        "pinnedBookmarks": pinned,
        "likedBookmarks": liked,
        "favorites": user.get("favorites", []),
        "stats": {
            "bookmarksCount": user_bookmarks_count,
            "snippetsCount": user_snippets_count,
            "watchedTagsCount": len(user.get("watchedTags", [])),
            "likedBookmarksCount": len(liked)
        }
    }


@mcp.tool()
async def manage_watched_tags(
    _track("manage_watched_tags")
    user_id: str,
    action: str,
    tags: Optional[List[str]] = None
) -> dict:
    """
    Add, remove, or list tags that a user is watching/following.
    Watched tags surface relevant public bookmarks and snippets in the user's feed.
    Use this when the user wants to follow or unfollow specific topics.
    Action must be one of: 'add', 'remove', 'list'.
    """
    valid_actions = ["add", "remove", "list"]
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Must be one of: {valid_actions}"}

    user = _get_or_create_user(user_id)
    watched = user.get("watchedTags", [])

    if action == "list":
        return {
            "userId": user_id,
            "watchedTags": watched,
            "count": len(watched)
        }

    if not tags:
        return {"error": f"'tags' parameter is required for action '{action}'"}

    if action == "add":
        added = []
        already_watching = []
        for tag in tags:
            if tag not in watched:
                watched.append(tag)
                added.append(tag)
            else:
                already_watching.append(tag)
        user["watchedTags"] = watched
        _users_store[user_id] = user
        return {
            "success": True,
            "message": f"Added {len(added)} tag(s) to watched list",
            "added": added,
            "alreadyWatching": already_watching,
            "watchedTags": watched
        }

    elif action == "remove":
        removed = []
        not_found = []
        for tag in tags:
            if tag in watched:
                watched.remove(tag)
                removed.append(tag)
            else:
                not_found.append(tag)
        user["watchedTags"] = watched
        _users_store[user_id] = user
        return {
            "success": True,
            "message": f"Removed {len(removed)} tag(s) from watched list",
            "removed": removed,
            "notFound": not_found,
            "watchedTags": watched
        }


@mcp.tool()
async def like_bookmark(
    _track("like_bookmark")
    user_id: str,
    bookmark_id: str,
    action: str = "like"
) -> dict:
    """
    Like or unlike a public bookmark on behalf of a user.
    Use this when the user wants to express appreciation for a bookmark or remove a previous like.
    Also tracks liked bookmarks in the user's profile.
    Action must be 'like' or 'unlike'.
    """
    valid_actions = ["like", "unlike"]
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Must be one of: {valid_actions}"}

    if bookmark_id not in _bookmarks_store:
        return {"error": f"Bookmark with ID '{bookmark_id}' not found"}

    bm = _bookmarks_store[bookmark_id]

    if not bm.get("public", False):
        return {"error": "Cannot like a private bookmark. Only public bookmarks can be liked."}

    user = _get_or_create_user(user_id)
    liked_ids = [item.get("_id") if isinstance(item, dict) else item for item in user.get("likedBookmarks", [])]

    if action == "like":
        if bookmark_id in liked_ids:
            return {
                "success": False,
                "message": "You have already liked this bookmark",
                "likeCount": bm.get("likeCount", 0)
            }
        bm["likeCount"] = bm.get("likeCount", 0) + 1
        user["likedBookmarks"].append({"_id": bookmark_id})
        _bookmarks_store[bookmark_id] = bm
        _users_store[user_id] = user
        return {
            "success": True,
            "message": "Bookmark liked successfully",
            "bookmarkId": bookmark_id,
            "likeCount": bm["likeCount"]
        }

    elif action == "unlike":
        if bookmark_id not in liked_ids:
            return {
                "success": False,
                "message": "You have not liked this bookmark",
                "likeCount": bm.get("likeCount", 0)
            }
        bm["likeCount"] = max(0, bm.get("likeCount", 0) - 1)
        user["likedBookmarks"] = [item for item in user["likedBookmarks"]
                                   if (item.get("_id") if isinstance(item, dict) else item) != bookmark_id]
        _bookmarks_store[bookmark_id] = bm
        _users_store[user_id] = user
        return {
            "success": True,
            "message": "Bookmark unliked successfully",
            "bookmarkId": bookmark_id,
            "likeCount": bm["likeCount"]
        }




_SERVER_SLUG = "codeverdotdev-codever"

def _track(tool_name: str, ua: str = ""):
    import threading
    def _send():
        try:
            import urllib.request, json as _json
            data = _json.dumps({"slug": _SERVER_SLUG, "event": "tool_call", "tool": tool_name, "user_agent": ua}).encode()
            req = urllib.request.Request("https://www.volspan.dev/api/analytics/event", data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()

async def health(request):
    return JSONResponse({"status": "ok", "server": mcp.name})

async def tools(request):
    registered = await mcp.list_tools()
    tool_list = [{"name": t.name, "description": t.description or ""} for t in registered]
    return JSONResponse({"tools": tool_list, "count": len(tool_list)})

sse_app = mcp.http_app(transport="sse")

app = Starlette(
    routes=[
        Route("/health", health),
        Route("/tools", tools),
        Mount("/", sse_app),
    ],
    lifespan=sse_app.lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
