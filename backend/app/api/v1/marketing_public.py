"""The one public door of Google Marketing Studio: a post photo, fetched by Google.

Google's Posts API accepts media only as a `sourceUrl` that Google downloads itself, so a private storage address cannot be used. An image is served here ONLY if it has a random
unguessable token, which is created the first time the owner attaches that image to a post. Documents are never served. The response carries nothing about the business.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import limit_by_ip
from app.models import MarketingAsset

router = APIRouter(prefix="/public/mm", tags=["public"])
TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,48}$")


@router.get("/{token}", dependencies=[Depends(limit_by_ip("mm-photo", settings.rl_public_scan_per_minute, 60))])
def post_photo(token: str, db: Session = Depends(public_db)):
    if not TOKEN.match(token):
        raise HTTPException(status_code=404, detail="Not found")
    a = db.scalar(select(MarketingAsset).where(MarketingAsset.public_token == token, MarketingAsset.kind == "image"))
    if not a:
        raise HTTPException(status_code=404, detail="Not found")
    db.refresh(a, ["data"])
    return Response(content=a.data, media_type=a.content_type, headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"})
