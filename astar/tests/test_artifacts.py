from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artifacts import ArtifactStore


class ArtifactStoreTests(unittest.TestCase):
    def test_write_json_writes_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(root=tmpdir)
            path = store.write_json("demo/output.json", {"value": 1})
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())["value"], 1)

    def test_write_json_uploads_to_gcs_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_blob = Mock()
            fake_bucket = Mock()
            fake_bucket.blob.return_value = fake_blob
            fake_client = Mock()
            fake_client.bucket.return_value = fake_bucket

            with patch("artifacts.storage") as fake_storage:
                fake_storage.Client.return_value = fake_client
                store = ArtifactStore(root=tmpdir, gcs_bucket="bucket-1", gcs_prefix="astar")
                store.write_json("demo/output.json", {"value": 1})

            fake_client.bucket.assert_called_once_with("bucket-1")
            fake_bucket.blob.assert_called_once()
            fake_blob.upload_from_filename.assert_called_once()


if __name__ == "__main__":
    unittest.main()
