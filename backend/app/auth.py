import hmac
import os
from typing import Optional

from fastapi import HTTPException


ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "denis")


def assert_admin_password(x_admin_password: Optional[str]) -> None:
    if not x_admin_password or not hmac.compare_digest(x_admin_password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Unauthorized")
