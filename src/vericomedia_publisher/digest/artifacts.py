"""AES-256-GCM envelope for public-repository Actions artifacts; no plaintext upload."""
import argparse
import base64
import io
import json
import os
import zipfile
from pathlib import Path
from .common import PipelineError

MAGIC=b'VERICO1'
AAD=b'vericomedia-editorial-artifacts-v1'
FILES=('research.json','draft.md','edited.md','article.html','publication-report.json','factcheck.json')


def key_from_env():
    try:key=base64.b64decode(os.environ['VERICO_ARTIFACT_KEY'],validate=True)
    except (KeyError,ValueError):raise PipelineError('missing_or_invalid_artifact_key') from None
    if len(key)!=32:raise PipelineError('artifact_key_must_be_32_bytes')
    return key


def archive(directory):
    directory=Path(directory);buffer=io.BytesIO()
    selected=[directory/f for f in FILES]+list((directory/'screenshots').glob('*.png'))+list((directory/'screenshots').glob('qa*.json'))
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for path in selected:
            if not path.exists():continue
            if path.is_symlink() or directory.resolve() not in path.resolve().parents:
                raise PipelineError('unsafe_artifact_path')
            z.write(path,path.relative_to(directory))
    return buffer.getvalue()


def seal(data,key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce=os.urandom(12)
    return MAGIC+nonce+AESGCM(key).encrypt(nonce,data,AAD)


def unseal(data,key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not data.startswith(MAGIC):raise PipelineError('unknown_artifact_envelope')
    return AESGCM(key).decrypt(data[len(MAGIC):len(MAGIC)+12],data[len(MAGIC)+12:],AAD)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['encrypt','decrypt'])
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--fixture-ephemeral',action='store_true')
    args=parser.parse_args(argv)
    if args.destination.exists():raise PipelineError('artifact_destination_exists')
    if args.fixture_ephemeral:
        report=json.loads((args.source/'publication-report.json').read_text())
        if args.operation!='encrypt' or report.get('fixture_only') is not True:
            raise PipelineError('ephemeral_key_allowed_only_for_synthetic_fixture')
        key=os.urandom(32)
    else:key=key_from_env()
    data=archive(args.source) if args.operation=='encrypt' else args.source.read_bytes()
    result=seal(data,key) if args.operation=='encrypt' else unseal(data,key)
    if args.operation=='encrypt' and unseal(result,key)!=data:raise PipelineError('artifact_roundtrip_failed')
    args.destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(args.destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as output:output.write(result)


if __name__=='__main__':main()
