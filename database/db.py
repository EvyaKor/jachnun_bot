"""
חיבור למסד הנתונים ואתחול טבלאות.
כולל פונקציה לזריעת נתוני התפריט הראשוניים.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, MenuItem
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jachnun.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """יוצר את כל הטבלאות במסד הנתונים."""
    Base.metadata.create_all(bind=engine)


def seed_menu():
    """
    זורע את פריטי התפריט הראשוניים אם הטבלה ריקה.
    מבוסס על תפריט ג'חנון אקספרס האמיתי.
    """
    db = SessionLocal()
    try:
        if db.query(MenuItem).count() == 0:
            menu_items = [
                MenuItem(
                    name="ג'חנון",
                    description="ג'חנון פרווה חם וטרי, מוגש עם רסק, ביצה וסחוג",
                    price=25.0,
                    is_dairy=False,
                    is_available=True,
                ),
                MenuItem(
                    name="קובנייה",
                    description="קובנייה חלבית חמה וטרייה, מוגשת עם רסק, ביצה וסחוג",
                    price=15.0,
                    is_dairy=True,
                    is_available=True,
                ),
            ]
            db.add_all(menu_items)
            db.commit()
    finally:
        db.close()


def get_db():
    """מחולל session למסד הנתונים לשימוש ב-FastAPI Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
