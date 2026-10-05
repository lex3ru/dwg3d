"""The furniture / equipment catalog; changes need "catalog_admin" (checked by the middleware)."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import catalog
from .common import mb, serve

router = APIRouter()
MAX_CATALOG_GLB = mb("DWG3D_MAX_CATALOG_GLB_MB", 50)


@router.get("/api/catalog")
def get_catalog():
    return catalog.as_json()


@router.post("/api/catalog/items", status_code=201)
def create_catalog_item(v: dict):
    return catalog.create_item(v)


@router.patch("/api/catalog/items/{iid}")
def update_catalog_item(iid: str, v: dict):
    return catalog.update_item(iid, v)


@router.post("/api/catalog/items/{iid}/model")
async def upload_catalog_model(iid: str, file: UploadFile = File(...)):
    data = await file.read(MAX_CATALOG_GLB + 1)
    if len(data) > MAX_CATALOG_GLB:
        raise HTTPException(413, "Файл слишком большой")
    return await run_in_threadpool(catalog.upload_model, iid, data)


@router.get("/api/catalog/models/{name}")
def get_catalog_model(name: str):
    key = catalog.model_key(name)
    if key is None:
        raise HTTPException(404)
    # file names carry a content hash: cache forever
    return serve(key, "model/gltf-binary", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/api/catalog/categories", status_code=201)
def create_catalog_category(v: dict):
    return catalog.save_category(v.get("id"), v, create=True)


@router.patch("/api/catalog/categories/{cid}")
def update_catalog_category(cid: str, v: dict):
    return catalog.save_category(cid, v, create=False)
