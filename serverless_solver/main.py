"""FastAPI entrypoint for Serverless Solver API (NuShift Solver-as-a-Service).

GCP Cloud Run / AWS Lambda Container / 独立コンテナとして起動し、
HTTP POST /api/v1/solve でステートレスに数理最適化シフト計算を提供する。
"""

from __future__ import annotations

import logging
from fastapi import FastAPI, HTTPException, status
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

# CORS設定（必要に応じて許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """コンテナ起動・ヘルスチェックエンドポイント。"""
    from shiftai.solver import is_highs_available
    return {
        "status": "healthy",
        "engine": "NuShift Core v0.8.0",
        "highs_available": is_highs_available(),
    }


@app.post(
    "/api/v1/solve",
    response_model=ShiftSolveResponse,
    status_code=status.HTTP_200_OK,
    summary="月次シフト数理最適化求解",
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
    except Exception as exc:
        logger.exception("エンドポイント内部エラー: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"求解処理中に予期せぬエラーが発生しました: {exc}",
        )
