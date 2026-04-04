"""
חיבור למסד הנתונים ואתחול טבלאות.
כולל פונקציה לזריעת נתוני התפריט הראשוניים.
"""

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from database.models import Base, MenuItem
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jachnun.db")

# SQLite: דורש check_same_thread=False ואינו תומך בהגדרות pool
# PostgreSQL: מוגדר עם pool_pre_ping וניהול חיבורים מתקדם
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,      # בודק חיבור לפני שימוש — מונע stale connections
        pool_size=10,            # חיבורים פעילים בו-זמנית
        max_overflow=20,         # חיבורים נוספים תחת עומס
        pool_recycle=3600,       # מחדש חיבורים כל שעה
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """יוצר את כל הטבלאות במסד הנתונים ומריץ מיגרציות בטוחות."""
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """
    מוסיף עמודות חסרות לטבלאות קיימות — בטוח להרצה חוזרת.
    מיועד לשדרוגים ללא Alembic.
    """
    try:
        inspector = inspect(engine)
        order_columns = [c["name"] for c in inspector.get_columns("orders")]
        with engine.connect() as conn:
            if "updated_at" not in order_columns:
                conn.execute(text("ALTER TABLE orders ADD COLUMN updated_at TIMESTAMP"))
                conn.commit()
                logger.info("מיגרציה: עמודת updated_at נוספה לטבלת orders")
    except Exception:
        logger.exception("שגיאה בהרצת מיגרציות")


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
