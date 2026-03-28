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

# SQLite דורש check_same_thread=False; Postgres לא תומך בזה
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """יוצר את כל הטבלאות במסד הנתונים."""
    Base.metadata.create_all(bind=engine)


def seed_menu():
    """
    זורע את פריטי התפריט אם הטבלה ריקה.
    מנות עיקריות + תוספות.
    """
    db = SessionLocal()
    try:
        if db.query(MenuItem).count() > 0:
            return

        menu_items = [
            # מנות עיקריות
            MenuItem(
                name="ג'חנון",
                description="ג'חנון חם וטרי, מוגש עם רסק עגניות, ביצה וסחוג",
                price=25.0,
                is_dairy=False,
                is_available=True,
                is_extra=False,
            ),
            MenuItem(
                name="קובנייה",
                description="קובנייה חלבית חמה וטרייה, מוגשת עם רסק עגניות, ביצה וסחוג",
                price=20.0,
                is_dairy=True,
                is_available=True,
                is_extra=False,
            ),
            # תוספות
            MenuItem(
                name="ביצה נוספת",
                description="ביצה קשה נוספת",
                price=3.0,
                is_dairy=False,
                is_available=True,
                is_extra=True,
            ),
            MenuItem(
                name="רסק עגניות + סחוג",
                description="תוספת רסק עגניות וסחוג",
                price=3.0,
                is_dairy=False,
                is_available=True,
                is_extra=True,
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
