"""
בדיקות מקיפות לבוט ג'חנון אקספרס.
מכסות: זרימת שיחה מלאה, מקרי קצה, מסד נתונים, לוגיקת שבת, משלוחים, תשלום.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch
from datetime import date

# אתחול מסד נתונים לבדיקות בזיכרון
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from database.db import init_db, seed_menu, SessionLocal
from database.models import Order, Customer, MenuItem
from handlers.message_handler import handle_message
from state_machine import reset_session, get_state, ChatState
from services.order_service import get_next_saturday

PHONE = "+972500000001"


@pytest.fixture(autouse=True)
def setup():
    """אתחול מסד נתונים ואיפוס session לפני כל בדיקה."""
    from database.models import Base
    from database.db import engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_menu()
    reset_session(PHONE)
    yield
    reset_session(PHONE)


# ============================================================
# 1. בדיקות זרימת שיחה בסיסית
# ============================================================

class TestBasicFlow:

    def test_greeting_any_message(self):
        """כל הודעה ראשונה מקבלת ברכה."""
        reply = handle_message(PHONE, "היי")
        assert "ג'חנון אקספרס" in reply
        assert "בני ברית" in reply

    def test_greeting_moves_to_browsing(self):
        """אחרי ברכה — המצב עובר ל-BROWSING_MENU."""
        handle_message(PHONE, "היי")
        assert get_state(PHONE) == ChatState.BROWSING_MENU

    def test_menu_command_shows_menu(self):
        """כתיבת 'תפריט' מציגה את התפריט ועוברת למצב הזמנה."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "תפריט")
        assert "ג'חנון" in reply
        assert "25" in reply
        assert "קובנייה" in reply
        assert "20" in reply

    def test_menu_switches_to_adding_items(self):
        """'תפריט' עובר למצב ADDING_ITEMS."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "תפריט")
        assert get_state(PHONE) == ChatState.ADDING_ITEMS

    def test_order_command_shows_menu(self):
        """כתיבת 'הזמנה' מציגה תפריט ועוברת למצב הוספה."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "הזמנה")
        assert "ג'חנון" in reply
        assert get_state(PHONE) == ChatState.ADDING_ITEMS


# ============================================================
# 2. בדיקות הוספה לסל
# ============================================================

class TestCart:

    def _start_ordering(self):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")

    def test_add_jachnun(self):
        """הוספת ג'חנון לסל."""
        self._start_ordering()
        reply = handle_message(PHONE, "1")
        assert "ג'חנון" in reply
        assert "25" in reply

    def test_add_kubane(self):
        """הוספת קובנייה לסל."""
        self._start_ordering()
        reply = handle_message(PHONE, "2")
        assert "קובנייה" in reply
        assert "20" in reply

    def test_add_multiple_items(self):
        """הוספת מספר פריטים — מחיר מצטבר נכון."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        reply = handle_message(PHONE, "2")
        assert "₪70" in reply  # 25+25+20

    def test_empty_cart_finish(self):
        """סיום עם סל ריק — מחזיר הודעת שגיאה."""
        self._start_ordering()
        reply = handle_message(PHONE, "סיום")
        assert "ריק" in reply

    def test_invalid_item_number(self):
        """מספר לא חוקי בתפריט — לא מוסיף לסל."""
        self._start_ordering()
        reply = handle_message(PHONE, "5")
        assert "לא הבנתי" in reply


# ============================================================
# 3. בדיקות לוגיקת משלוח
# ============================================================

class TestDelivery:

    def _fill_cart(self, total_above_70=True):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        if total_above_70:
            handle_message(PHONE, "1")  # 25
            handle_message(PHONE, "1")  # 25
            handle_message(PHONE, "1")  # 25 = 75 total
        else:
            handle_message(PHONE, "1")  # 25 only
        handle_message(PHONE, "סיום")

    def test_delivery_options_shown(self):
        """אפשרויות משלוח מוצגות אחרי סיום."""
        self._fill_cart()
        state = get_state(PHONE)
        assert state == ChatState.CHOOSING_DELIVERY

    def test_self_pickup(self):
        """בחירת איסוף עצמי — ללא עלות משלוח."""
        self._fill_cart()
        reply = handle_message(PHONE, "1")
        assert "איסוף עצמי" in reply

    def test_delivery_hod_hasharon(self):
        """משלוח להוד השרון — ₪15."""
        self._fill_cart(total_above_70=True)
        reply = handle_message(PHONE, "2")
        assert "הוד השרון" in reply

    def test_delivery_kfar_saba(self):
        """משלוח לכפר סבא — ₪25."""
        self._fill_cart(total_above_70=True)
        reply = handle_message(PHONE, "3")
        assert "כפר סבא" in reply

    def test_delivery_below_minimum(self):
        """משלוח עם סל מתחת ל-₪70 — הודעת שגיאה."""
        self._fill_cart(total_above_70=False)
        reply = handle_message(PHONE, "2")
        assert "מינימום" in reply or "70" in reply

    def test_delivery_cost_added_to_total(self):
        """עלות משלוח מתווספת לסכום הכולל."""
        self._fill_cart(total_above_70=True)
        handle_message(PHONE, "2")  # הוד השרון +15
        handle_message(PHONE, "טסט")  # שם
        reply = handle_message(PHONE, "09:00")  # שעה
        assert "₪90" in reply  # 75 + 15


# ============================================================
# 4. בדיקות זרימת אישור מלאה
# ============================================================

class TestFullOrderFlow:

    def _complete_order(self, delivery="1", payment="1", name="טסט"):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, delivery)
        handle_message(PHONE, name)
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        return handle_message(PHONE, payment)

    def test_order_confirmed_cash(self):
        """הזמנה מלאה עם תשלום במזומן."""
        reply = self._complete_order(payment="1")
        assert "אושרה" in reply
        assert "מזומן" in reply

    def test_order_confirmed_bit(self):
        """הזמנה עם תשלום בביט — מציג מספר טלפון."""
        reply = self._complete_order(payment="2")
        assert "אושרה" in reply
        assert "054-2380330" in reply

    def test_order_confirmed_paybox(self):
        """הזמנה עם תשלום בפייבוקס — מציג מספר טלפון."""
        reply = self._complete_order(payment="3")
        assert "אושרה" in reply
        assert "054-2380330" in reply

    def test_order_saved_to_db(self):
        """הזמנה נשמרת במסד הנתונים."""
        self._complete_order()
        db = SessionLocal()
        orders = db.query(Order).all()
        db.close()
        assert len(orders) == 1

    def test_customer_saved_to_db(self):
        """לקוח נשמר במסד הנתונים."""
        self._complete_order(name="ישראל ישראלי")
        db = SessionLocal()
        customer = db.query(Customer).filter(Customer.phone_number == PHONE).first()
        db.close()
        assert customer is not None
        assert customer.name == "ישראל ישראלי"

    def test_session_reset_after_order(self):
        """ה-session מתאפס לאחר אישור הזמנה."""
        self._complete_order()
        assert get_state(PHONE) == ChatState.GREETING

    def test_cancel_order(self):
        """ביטול הזמנה — session מתאפס."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        reply = handle_message(PHONE, "ביטול")
        assert "בוטלה" in reply
        assert get_state(PHONE) == ChatState.GREETING


# ============================================================
# 5. בדיקות לוגיקת שבת
# ============================================================

class TestSaturdayLogic:

    def test_next_saturday_is_saturday(self):
        """הפונקציה תמיד מחזירה יום שבת."""
        saturday_str = get_next_saturday()
        saturday_date = date.strptime(saturday_str, "%d/%m/%Y") if hasattr(date, 'strptime') else None
        from datetime import datetime
        d = datetime.strptime(saturday_str, "%d/%m/%Y").date()
        assert d.weekday() == 5  # 5 = שבת

    def test_next_saturday_not_today_if_saturday(self):
        """אם היום שבת — מחזיר את השבת הבאה ולא היום."""
        with patch("services.order_service.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 4)  # שבת
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            saturday_str = get_next_saturday()
            from datetime import datetime
            d = datetime.strptime(saturday_str, "%d/%m/%Y").date()
            assert d > date(2026, 4, 4)

    def test_order_date_shown_in_confirmation(self):
        """תאריך השבת מופיע בהודעת האישור."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "הזמנה")
        assert "/" in reply  # תאריך בפורמט DD/MM/YYYY


# ============================================================
# 6. בדיקות מקרי קצה
# ============================================================

class TestEdgeCases:

    def test_unknown_message_returns_help(self):
        """הודעה לא מובנת מחזירה הוראות עזרה."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "בלבול")
        assert "לא הבנתי" in reply

    def test_multiple_sessions_independent(self):
        """שני לקוחות שונים — sessions עצמאיים."""
        phone2 = "+972500000002"
        reset_session(phone2)

        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")

        handle_message(phone2, "היי")

        assert get_state(PHONE) == ChatState.ADDING_ITEMS
        assert get_state(phone2) == ChatState.BROWSING_MENU

        reset_session(phone2)

    def test_invalid_payment_choice(self):
        """בחירת אמצעי תשלום לא חוקי."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        reply = handle_message(PHONE, "9")  # מספר לא חוקי
        assert "1" in reply and "2" in reply and "3" in reply

    def test_menu_items_exist_in_db(self):
        """פריטי התפריט קיימים במסד הנתונים."""
        db = SessionLocal()
        items = db.query(MenuItem).all()
        db.close()
        assert len(items) == 2
        names = [i.name for i in items]
        assert "ג'חנון" in names
        assert "קובנייה" in names

    def test_jachnun_price(self):
        """מחיר ג'חנון נכון — ₪25."""
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        db.close()
        assert item.price == 25.0

    def test_kubane_price(self):
        """מחיר קובנייה נכון — ₪20."""
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "קובנייה").first()
        db.close()
        assert item.price == 20.0
