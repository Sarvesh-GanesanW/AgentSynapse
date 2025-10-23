"""
JSON serialization utilities for handling special types like Decimal
"""

import json
from decimal import Decimal
from typing import Any


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Decimal types from DynamoDB

    DynamoDB returns numeric values as Decimal objects which are not
    JSON serializable by default. This encoder converts them to float.
    """
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            # Convert Decimal to float for JSON serialization
            return float(obj)
        return super().default(obj)


def dumps_with_decimal(obj: Any, **kwargs) -> str:
    """
    Convenience function to serialize objects that may contain Decimal types

    Args:
        obj: Object to serialize
        **kwargs: Additional arguments to pass to json.dumps

    Returns:
        JSON string representation
    """
    return json.dumps(obj, cls=DecimalEncoder, **kwargs)
