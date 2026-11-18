"""Verify the versioned website payload, then extract it for GitHub Pages."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
DESTINATION = ROOT / '_site'
LIMIT = 1_000_000_000


def build():
    manifest = json.loads((PAYLOAD / 'manifest.json').read_text())
    if manifest.get('version') != 1 or not isinstance(manifest.get('parts'), list):
        raise ValueError('Unsupported payload manifest')
    parts = manifest['parts']
    if not parts or manifest.get('extractedBytes', LIMIT) >= LIMIT:
        raise ValueError('Website exceeds the GitHub Pages size limit')
    expected_names = [f'site-{i:03d}.part' for i in range(len(parts))]
    if [part.get('name') for part in parts] != expected_names:
        raise ValueError('Payload parts must be complete and sequential')
    if sorted(p.name for p in PAYLOAD.glob('*.part')) != expected_names:
        raise ValueError('Payload parts do not match the manifest')
    if DESTINATION.exists():
        raise ValueError('The website destination already exists')
    with tempfile.TemporaryDirectory(prefix='village-pages-') as temporary:
        archive = Path(temporary) / 'site.zip'
        combined_hash = sha256()
        combined_bytes = 0
        with archive.open('wb') as output:
            for part in parts:
                digest = sha256()
                size = 0
                with (PAYLOAD / part['name']).open('rb') as source:
                    while chunk := source.read(4 * 1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        combined_hash.update(chunk)
                        size += len(chunk)
                if size != part['bytes'] or digest.hexdigest() != part['sha256']:
                    raise ValueError('Payload verification failed: ' + part['name'])
                combined_bytes += size
        if combined_bytes != manifest['archiveBytes'] or combined_hash.hexdigest() != manifest['archiveSha256']:
            raise ValueError('The combined website archive could not be verified')
        with ZipFile(archive) as site:
            entries = site.infolist()
            total = sum(entry.file_size for entry in entries)
            if total != manifest['extractedBytes'] or total >= LIMIT:
                raise ValueError('Incorrect website size')
            seen = set()
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                mode = entry.external_attr >> 16
                if (not name or '\\' in name or path.is_absolute() or '..' in path.parts
                        or ':' in name or name in seen or stat.S_ISLNK(mode)
                        or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))):
                    raise ValueError('Invalid website archive path')
                seen.add(name)
            required = {'index.html', 'viewer/index.html', 'viewer/app.js',
                        'viewer/streaming.js', 'data-stream/manifest.json'}
            if not required.issubset(seen):
                raise ValueError('Required website files are missing')
            DESTINATION.mkdir()
            for entry in entries:
                target = DESTINATION / entry.filename
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with site.open(entry) as source, target.open('wb') as output:
                        shutil.copyfileobj(source, output)
    print(f'Verified and extracted {total:,} bytes for GitHub Pages.')


if __name__ == '__main__':
    build()
