
from fastapi import FastAPI
from sqlalchemy import select
from app import SessionLocal, Document

api = FastAPI()

@api.get("/documents")
def list_documents():
    with SessionLocal() as db:
        docs = db.execute(select(Document)).scalars().all()
        return [{"id":d.id,"name":d.doc_name,"status":d.status} for d in docs]
