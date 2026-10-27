import base64
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from vericomedia_publisher.digest.artifacts import archive,seal,unseal,key_from_env,main
from vericomedia_publisher.digest.common import PipelineError

class ArtifactTests(unittest.TestCase):
    def test_encryption_roundtrip_tamper_and_wrong_key(self):
        key=os.urandom(32);data=b'private editorial text'
        sealed=seal(data,key)
        self.assertNotIn(data,sealed);self.assertEqual(unseal(sealed,key),data)
        for candidate,secret in [(sealed[:-1]+bytes([sealed[-1]^1]),key),(sealed,os.urandom(32))]:
            with self.assertRaises(Exception):unseal(candidate,secret)

    def test_archive_excludes_secrets_and_session_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'draft.md').write_text('draft');(root/'.env').write_text('synthetic secret');(root/'state.json').write_text('session')
            with zipfile.ZipFile(io.BytesIO(archive(root))) as z:self.assertEqual(z.namelist(),['draft.md'])

    def test_ephemeral_key_refused_for_real_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'publication-report.json').write_text(json.dumps({'fixture_only':False}))
            with self.assertRaises(PipelineError):main(['encrypt',str(root),str(root/'out.enc'),'--fixture-ephemeral'])

    def test_key_format(self):
        with patch.dict(os.environ,{'VERICO_ARTIFACT_KEY':base64.b64encode(b'x'*32).decode()}):self.assertEqual(key_from_env(),b'x'*32)
        with patch.dict(os.environ,{'VERICO_ARTIFACT_KEY':'invalid'}):
            with self.assertRaises(PipelineError):key_from_env()
