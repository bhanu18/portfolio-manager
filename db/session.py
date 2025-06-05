from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os

# --- UPDATED FOR MYSQL ---
# The format is mysql+aiomysql://<user>:<password>@<host>:<port>/<dbname>
DATABASE_URL = os.environ.get("DB_URL_MAIN")

# The rest of the file is the same
engine = create_async_engine(DATABASE_URL, echo=True)

AsyncSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession
)