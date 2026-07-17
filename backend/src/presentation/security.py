"""API 安全层（P1-3）。

- 当 config.settings.API_TOKEN 为空时：开放模式，所有接口直接放行（本地开发）。
- 当设置了 API_TOKEN 时：所有经本依赖保护的接口必须携带
  `Authorization: Bearer <API_TOKEN>`，否则返回 401。

用法：在 APIRouter 上挂 `dependencies=[Depends(require_auth)]` 即可全路由生效。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from config import settings

_bearer = HTTPBearer(auto_error=False)


async def require_auth(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> None:
    """全局鉴权依赖；API_TOKEN 为空时为 no-op。"""
    if not settings.API_TOKEN:
        return  # 本地开发：开放模式
    if not creds or creds.credentials != settings.API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少或非法的 API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
