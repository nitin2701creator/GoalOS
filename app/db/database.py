from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL="sqlite:///goalos.db"
engine=create_engine(DATABASE_URL, future=True)
SessionLocal=sessionmaker(bind=engine)
