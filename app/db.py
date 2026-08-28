import os

from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine

import app.schema  
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing from .env")


engine = create_engine(DATABASE_URL)


def create_tables():
    SQLModel.metadata.create_all(engine)
    