"""
מודלים של מסד הנתונים עבור ג'חנון אקספרס.
טבלאות: לקוחות, פריטי תפריט, הזמנות, פריטי הזמנה.
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class Customer(Base):
    """לקוח רשום במערכת."""

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")


class MenuItem(Base):
    """פריט תפריט."""

    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    is_dairy = Column(Boolean, default=False)
    is_available = Column(Boolean, default=True)

    order_items = relationship("OrderItem", back_populates="menu_item")


class Order(Base):
    """הזמנה של לקוח."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    status = Column(String, default="ממתין")  # ממתין / אושר / בוטל
    pickup_date = Column(String, nullable=True)   # תאריך שבת — נקבע אוטומטית
    pickup_time = Column(String, nullable=True)   # שעת איסוף — נבחרת על ידי הלקוח
    notes = Column(Text, nullable=True)
    total_price = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    """פריט בתוך הזמנה."""

    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=False)
    quantity = Column(Integer, default=1)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")
