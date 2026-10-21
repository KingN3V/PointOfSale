from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip(request: Request) -> str:
    return request.headers.get("true-client-ip") or get_remote_address(request)


limiter = Limiter(key_func=client_ip)