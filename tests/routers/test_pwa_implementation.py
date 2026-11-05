"""PWA（Progressive Web App）実装の統合テスト。

guardian キオスク、parent-portal、nushift ランディングページの
PWA対応状況を検証する。

テスト対象:
- manifest.webmanifest の妥当性（start_url, scope, display, icons）
- service-worker.js エンドポイントの Content-Type と Service-Worker-Allowed ヘッダー
- PNG アイコンの存在と PNG シグネチャ
- base.html による beforeinstallprompt インストール促進 UI の注入
"""

from __future__ import annotations

import json
import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import routers.guardian as guardian_module
import routers.parent_portal as parent_portal_module
import routers.parent_push as parent_push_module
from testing_helpers import configure_test_environment


def _build_test_app() -> FastAPI:
    configure_test_environment()
    app = FastAPI()
    app.include_router(guardian_module.router)
    app.include_router(parent_portal_module.router)
    app.include_router(parent_portal_module.mock_login_router)
    app.include_router(parent_push_module.router)
    app.include_router(parent_push_module.settings_router)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[guardian_module.get_session] = override_get_session
    app.dependency_overrides[parent_portal_module.get_session] = override_get_session
    app.dependency_overrides[parent_push_module.get_session] = override_get_session
    return app


class GuardianPwaTests(unittest.TestCase):
    """guardian キオスクの PWA 対応テスト。"""

    def setUp(self):
        self.app = _build_test_app()
        self.client = TestClient(self.app)

    def test_guardian_manifest_structure(self):
        """guardian/manifest.webmanifest が PWA として必須フィールドを持つこと。"""
        response = self.client.get("/guardian/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/manifest+json")

        manifest = response.json()
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "/guardian/")
        self.assertEqual(manifest["lang"], "ja")
        self.assertGreaterEqual(len(manifest["icons"]), 1)
        for icon in manifest["icons"]:
            self.assertIn("type", icon)
            self.assertEqual(icon["type"], "image/png")

    def test_guardian_manifest_icons_exist_and_are_png(self):
        """manifest に列挙された全アイコンが存在し、PNG シグネチャを持つこと。"""
        response = self.client.get("/guardian/manifest.webmanifest")
        manifest = response.json()
        for icon in manifest["icons"]:
            image = self.client.get(icon["src"])
            self.assertEqual(image.status_code, 200, f"アイコン {icon['src']} が見つかりません")
            self.assertEqual(
                image.content[:8],
                b"\x89PNG\r\n\x1a\n",
                f"アイコン {icon['src']} は PNG ではありません",
            )

    def test_guardian_service_worker_headers(self):
        """guardian-service-worker.js が正しい Content-Type と SW-Allowed ヘッダーを返すこと。"""
        response = self.client.get("/guardian/guardian-service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/javascript")
        self.assertEqual(
            response.headers["service-worker-allowed"],
            "/guardian/",
        )
        cache_control = response.headers.get("cache-control", "")
        self.assertTrue(
            "no-cache" in cache_control or "no-store" in cache_control,
            f"キャッシュ制御ヘッダーが見つかりません: {cache_control}",
        )


class ParentPortalPwaTests(unittest.TestCase):
    """parent-portal の PWA 対応テスト。"""

    def setUp(self):
        self.app = _build_test_app()
        self.client = TestClient(self.app)

    def test_parent_portal_manifest_structure(self):
        """parent-portal/manifest.webmanifest が PWA として必須フィールドを持つこと。"""
        response = self.client.get("/parent-portal/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/manifest+json")

        manifest = response.json()
        self.assertEqual(manifest["start_url"], "/parent-portal/")
        self.assertEqual(manifest["scope"], "/parent-portal/")
        self.assertEqual(manifest["display"], "standalone")

    def test_parent_portal_manifest_has_png_icons(self):
        """manifest に PNG アイコン（192x192, 512x512）が含まれること。"""
        response = self.client.get("/parent-portal/manifest.webmanifest")
        manifest = response.json()
        icon_sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertIn("192x192", icon_sizes)
        self.assertIn("512x512", icon_sizes)
        png_icons = [i for i in manifest["icons"] if i["type"] == "image/png"]
        self.assertGreaterEqual(len(png_icons), 1)

    def test_parent_portal_png_icons_exist(self):
        """icon-192.png と icon-512.png が存在し、PNG シグネチャを持つこと。"""
        for path in ("/parent-portal/icon-192.png", "/parent-portal/icon-512.png"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, f"{path} が見つかりません")
            self.assertEqual(response.content[:8], b"\x89PNG\r\n\x1a\n")

    def test_parent_portal_service_worker_headers(self):
        """push-service-worker.js が正しい Content-Type と SW-Allowed ヘッダーを返すこと。"""
        response = self.client.get("/parent-portal/push-service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/javascript")
        self.assertEqual(
            response.headers["service-worker-allowed"],
            "/parent-portal/",
        )


class BaseTemplatePwaTests(unittest.TestCase):
    """base.html の PWA インストール促進 UI テスト。"""

    def setUp(self):
        self.app = _build_test_app()
        self.client = TestClient(self.app)

    def test_parent_portal_template_includes_install_banner(self):
        """parent-portal ページに PWA インストール促進バナーが含まれること。"""
        response = self.client.get("/parent-portal/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("pwa-install-banner", html)
        self.assertIn("beforeinstallprompt", html)


class NushiftPwaTests(unittest.TestCase):
    """nushift ランディングページの PWA 対応テスト（ファイルベース）。"""

    MANIFEST_PATH = "e:/nushift/nushift/landing_page/manifest.webmanifest"
    INDEX_PATH = "e:/nushift/nushift/landing_page/index.html"
    SW_PATH = "e:/nushift/nushift/landing_page/sw.js"

    def test_nushift_manifest_exists_and_is_valid(self):
        """nushift/manifest.webmanifest が存在し、JSON としてパースできること。"""
        self.assertTrue(os.path.exists(self.MANIFEST_PATH), "manifest.webmanifest が見つかりません")
        with open(self.MANIFEST_PATH, encoding="utf-8-sig") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["lang"], "ja")
        self.assertGreaterEqual(len(manifest["icons"]), 1)

    def test_nushift_index_links_manifest(self):
        """nushift/index.html に manifest へのリンクが含まれること。"""
        self.assertTrue(os.path.exists(self.INDEX_PATH), "index.html が見つかりません")
        with open(self.INDEX_PATH, encoding="utf-8") as f:
            html = f.read()
        self.assertIn('rel="manifest"', html)
        self.assertIn('name="theme-color"', html)

    def test_nushift_service_worker_exists(self):
        """nushift/sw.js が存在し、サービスワーカーとしての最低構造を持つこと。"""
        self.assertTrue(os.path.exists(self.SW_PATH), "sw.js が見つかりません")
        with open(self.SW_PATH, encoding="utf-8") as f:
            sw = f.read()
        self.assertIn("self.addEventListener", sw)
        self.assertIn("install", sw)
        self.assertIn("fetch", sw)
        self.assertIn("activate", sw)

    def test_nushift_index_registers_service_worker(self):
        """nushift/index.html に serviceWorker 登録スクリプトが含まれること。"""
        with open(self.INDEX_PATH, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("serviceWorker", html)
        self.assertIn("navigator.serviceWorker.register", html)


if __name__ == "__main__":
    unittest.main()
