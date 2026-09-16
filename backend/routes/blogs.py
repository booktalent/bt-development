"""Blogs / CMS endpoints."""
from __future__ import annotations
from typing import Callable, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class BlogBody(BaseModel):
    title: str
    slug: str
    content: str
    cover_image: Optional[str] = None
    excerpt: str = ""
    tags: List[str] = []
    published: bool = True
    author: str = ""
    # Iter 41 — per-article featured banner (hero on /blog/<slug>)
    hero_image: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    hero_cta_label: Optional[str] = None
    hero_cta_url: Optional[str] = None


def make_router(
    *,
    db,
    admin_only: Callable,
    utcnow: Callable,
    new_id: Callable,
    clean: Callable,
) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/blogs")
    async def admin_list_blogs(_: dict = Depends(admin_only)):
        docs = await db.blogs.find({}).sort("created_at", -1).to_list(500)
        return [clean(d) for d in docs]

    @r.post("/admin/blogs")
    async def admin_create_blog(body: BlogBody, _: dict = Depends(admin_only)):
        if await db.blogs.find_one({"slug": body.slug}):
            raise HTTPException(400, "Slug already exists")
        doc = body.model_dump()
        doc["id"] = new_id()
        doc["created_at"] = utcnow()
        doc["updated_at"] = utcnow()
        await db.blogs.insert_one(doc)
        return clean(doc)

    @r.put("/admin/blogs/{bid}")
    async def admin_update_blog(bid: str, body: BlogBody, _: dict = Depends(admin_only)):
        doc = await db.blogs.find_one({"id": bid})
        if not doc:
            raise HTTPException(404, "Not found")
        updates = body.model_dump()
        updates["updated_at"] = utcnow()
        await db.blogs.update_one({"id": bid}, {"$set": updates})
        return clean(await db.blogs.find_one({"id": bid}))

    @r.delete("/admin/blogs/{bid}")
    async def admin_delete_blog(bid: str, _: dict = Depends(admin_only)):
        await db.blogs.delete_one({"id": bid})
        return {"ok": True}

    @r.get("/blogs")
    async def list_blogs(published_only: bool = True):
        q = {"published": True} if published_only else {}
        docs = await db.blogs.find(q).sort("created_at", -1).to_list(100)
        return [clean(d) for d in docs]

    @r.get("/blogs/{slug}")
    async def get_blog(slug: str):
        doc = await db.blogs.find_one({"slug": slug})
        if not doc:
            raise HTTPException(404, "Not found")
        return clean(doc)

    return r
