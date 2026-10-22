"""Decimal values stored as MongoDB Decimal128."""

from decimal import Decimal

from bson import Decimal128


def to_decimal128(amount: Decimal) -> Decimal128:
    return Decimal128(amount)


def from_decimal128(value: object) -> Decimal:
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, Decimal):
        return value
    raise TypeError(f"unsupported money value: {type(value).__name__}")
