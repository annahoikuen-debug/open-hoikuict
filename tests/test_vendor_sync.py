from scripts.sync_nushift_vendor import compute_file_hash, verify, DEFAULT_SOURCE


class TestVendorSync:
    """upstream と vendor の同期検証ツールのテスト。"""

    def test_current_upstream_and_vendor_are_in_sync(self):
        """現在の upstream (nushift) と vendor (openict) のファイルが100%一致していること。"""
        if DEFAULT_SOURCE.is_dir():
            assert verify(DEFAULT_SOURCE) is True

    def test_verify_detects_hash_mismatch(self, tmp_path):
        """ファイル内容の差分がある場合に verify が False を返すこと。"""
        mock_source = tmp_path / "nushift"
        mock_src_shiftai = mock_source / "src" / "shiftai"
        mock_src_shiftai.mkdir(parents=True)

        # 1つだけ差分ファイルを作成
        dummy_file = mock_src_shiftai / "domain.py"
        dummy_file.write_text("# modified content", encoding="utf-8")

        # verify は False になるべき
        assert verify(mock_source) is False

    def test_compute_file_hash(self, tmp_path):
        """compute_file_hash が決定論的な SHA-256 ハッシュを返すこと。"""
        test_file = tmp_path / "sample.txt"
        test_file.write_bytes(b"hello nushift")
        h1 = compute_file_hash(test_file)
        h2 = compute_file_hash(test_file)
        assert h1 == h2
        assert len(h1) == 64
