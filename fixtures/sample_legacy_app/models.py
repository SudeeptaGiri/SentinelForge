"""Data models for legacy order service."""

from dataclasses import dataclass


@dataclass
class OrderCreateRequest:
    customer_id: str
    item_id: str
    amount: float
    currency: str = "USD"
