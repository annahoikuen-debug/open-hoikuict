"""FastAPI entrypoint for Serverless Solver API (NuShift Solver-as-a-Service).

GCP Cloud Run / AWS Lambda Container / 独立コンテナとして起動し、
HTTP POST /api/v1/solve でステートレスに数理最適化シフト計算を提供する。
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .adapter import execute_solve
from .schema import ShiftSolveRequest, ShiftSolveResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [serverless-solver] %(message)s",
)
logger = logging.getLogger("serverless_solver")

app = FastAPI(
    title="NuShift Serverless Solver API",
    version="1.0.0",
    description="職員配置基準連動型 数理最適化シフト自動生成 サーバーレス計算API",
)

# サーバー間通信前提のため、明示指定されたオリジンのみ許可し資格情報共有は行わない
_cors_raw = os.getenv("SERVERLESS_CORS_ORIGINS", "")
_cors_origins = [o.strip().rstrip("/") for o in _cors_raw.split(",") if o.strip() and o.strip() != "*"]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["POST", "GET"],
        allow_headers=["Authorization", "Content-Type"],
    )


def _require_solver_auth(request: Request) -> None:
    """Bearer トークン検証（本番時は必須、トークン未設定の開発/テスト環境のみスキップ可）。"""
    expected = (os.getenv("HOIKUICT_SERVERLESS_SOLVER_TOKEN") or "").strip()
    is_prod = (os.getenv("HOIKUICT_ENV") or "production").strip().lower() == "production"
    auth_header = request.headers.get("authorization", "")

    if expected:
        if auth_header.startswith("Bearer "):
            presented = auth_header.removeprefix("Bearer ").strip()
            if hmac.compare_digest(presented, expected):
                return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="サーバーレスソルバーAPIの認証に失敗しました。",
        )

    if is_prod:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HOIKUICT_SERVERLESS_SOLVER_TOKEN が本番環境に設定されていません。",
        )


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """コンテナ起動・ヘルスチェックエンドポイント。"""
    import shiftai
    from shiftai.solver import is_highs_available

    return {
        "status": "healthy",
        "engine": f"NuShift Core v{getattr(shiftai, '__version__', '0.8.1')}",
        "highs_available": is_highs_available(),
    }


@app.post(
    "/api/v1/solve",
    response_model=ShiftSolveResponse,
    status_code=status.HTTP_200_OK,
    summary="月次シフト数理最適化求解",
    dependencies=[Depends(_require_solver_auth)],
)
def solve_shift_endpoint(request: ShiftSolveRequest) -> ShiftSolveResponse:
    """ステートレス数理最適化求解エンドポイント。

    DB接続を持たず、渡されたJSONリクエストのみから高速計算を行い、結果JSONを返却します。
    """
    logger.info("リクエスト受信: facility_id=%s, month=%s", request.facility_id, request.target_month)
    try:
        response = execute_solve(request)
        logger.info("求解完了: status=%s, elapsed=%.3fs", response.status, response.elapsed_sec)
        return response
    except Exception:
        logger.exception("エンドポイント内部エラー")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="求解処理中に内部エラーが発生しました。",
        )
