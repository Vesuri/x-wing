#!/usr/bin/env python3
"""Publish the release archive on GitHub (docs/release.md, "Publishing").

    make publish [PUBLISH=1]

Adapted from the WHDLoad project's common/tools/publish_release.py. From VERSION and the
release date it derives:
  tag      the version (0.1), a lightweight tag on HEAD, the commit whose build outputs
           the archive was just checked against (make publish)
  title    X-Wing <version> (dd.mm.yyyy)
  notes    the early-alpha notice and the change points of the version's history entry in
           the archive's ReadMe
Without PUBLISH=1 it only prints them. With it, it checks the GitHub account, that HEAD is
on main on GitHub and that the tag and release do not exist, then tags, creates the release
(a prerelease while the version is below 1.0), uploads the archive and its .sha256 and
downloads the archive again to compare. GitHub's API fails intermittently, so every remote
step is retried and checked by reading the state back.
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_release import DATE  # noqa: E402
from package_release import PREFIX  # noqa: E402

OWNER = 'Vesuri'
GH_REPO = f'{OWNER}/x-wing'
RELEASES = f'https://github.com/{GH_REPO}/releases/tag/'
README = f'https://github.com/{GH_REPO}#what-to-expect-from-01'


def run(*cmd, check=True):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f'{" ".join(cmd)} failed:\n{r.stdout}{r.stderr}')
    return r


def retry(step, done, what, tries=5):
    """Run step until done() holds; GitHub sometimes fails a request it then performs."""
    for attempt in range(tries):
        if done():
            return
        step()
        if done():
            return
        time.sleep(2 * (attempt + 1))
    sys.exit(f'{what} failed after {tries} attempts')


def notes_of(archive, version):
    """The early-alpha notice, then the version's history entry items, as Markdown."""
    readme = run('lha', 'pq', str(archive), f'{PREFIX}/ReadMe').stdout
    lines = readme.split('\n')
    head = re.compile(rf'^\s*version\s+{re.escape(version)}\s*\(')
    start = next((i for i, line in enumerate(lines) if head.match(line)), None)
    if start is None:
        sys.exit(f'the ReadMe has no history entry "version {version} (...)"')
    items = []
    for line in lines[start + 1:]:
        if not line.strip() or re.match(r'^\s*version\s', line):
            break
        text = line.strip()
        if text.startswith('- '):
            items.append(text[2:])
        elif items:
            items[-1] += ' ' + text
        else:
            sys.exit(f'unexpected line in the version {version} entry: {line!r}')
    if not items:
        sys.exit(f'the version {version} entry lists no changes')
    notice = ('**Early alpha, completely unoptimized.** Expect it to be slow and to stop on '
              'paths the tests have not reached; it needs more than 8 MB Fast RAM under '
              f'WHDLoad. Read [what to expect]({README}) before installing.\n\n')
    return notice + ''.join(f'- {i}\n' for i in items) + (
        '\nThe game files are not included: the installer installs them from your own five '
        'X-Wing 1.0 PC floppies.\n')


def gh_api(path, jq, tries=5):
    """The jq result for repos/<repo>/<path>, or None when GitHub answers 404."""
    for attempt in range(tries):
        r = run('gh', 'api', f'repos/{GH_REPO}/{path}', '--jq', jq, check=False)
        if r.returncode == 0:
            return r.stdout.strip()
        if 'HTTP 404' in r.stderr:
            return None
        time.sleep(2 * (attempt + 1))
    sys.exit(f'GitHub API {path} failed:\n{r.stderr}')


def remote_tag(tag):
    return gh_api(f'git/ref/tags/{tag}', '.object.sha') or None


def release_exists(tag):
    return run('gh', 'release', 'view', tag, '-R', GH_REPO, check=False).returncode == 0


def asset_count(tag):
    r = run('gh', 'release', 'view', tag, '-R', GH_REPO, '--json', 'assets',
            '--jq', '.assets|length', check=False)
    return int(r.stdout.strip() or 0) if r.returncode == 0 else 0


def push(refspec):
    """git push to origin; when SSH fails, over HTTPS with the gh account's credential."""
    try:
        if subprocess.run(['git', 'push', '-q', 'origin', refspec], cwd=ROOT,
                          capture_output=True, timeout=30).returncode == 0:
            return
    except subprocess.TimeoutExpired:
        pass
    run('git', '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
        'push', '-q', f'https://{OWNER}@github.com/{GH_REPO}.git', refspec, check=False)


def main():
    version = (ROOT / 'VERSION').read_text().strip()
    archive = ROOT / f'dist/XWing-{version}.lha'
    digest = ROOT / f'dist/XWing-{version}.lha.sha256'
    for p in (archive, digest):
        if not p.is_file():
            sys.exit(f'{p} missing: make publish writes it')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest.read_text().split()[0]:
        sys.exit(f'{archive.name} does not match {digest.name}')
    tag, title = version, f'X-Wing {version} ({DATE})'
    prerelease = int(version.split('.')[0]) < 1
    notes = notes_of(archive, version)
    head = run('git', 'rev-parse', 'HEAD').stdout.strip()
    print(f'tag      {tag} on {head[:8]} ({run("git", "log", "-1", "--format=%s").stdout.strip()})')
    print(f'title    {title}' + (' (prerelease)' if prerelease else ''))
    print(f'files    {archive.name}, {digest.name}')
    print('notes')
    print(''.join(f'         {line}\n' for line in notes.splitlines()), end='')
    if os.environ.get('PUBLISH') != '1':
        print('dry run: make publish PUBLISH=1 publishes this')
        return

    login = run('gh', 'api', 'user', '--jq', '.login').stdout.strip()
    if login != OWNER:
        sys.exit(f'the active GitHub account is {login}, not {OWNER} (gh auth switch)')
    status = gh_api(f'compare/{head}...main', '.status')
    if status not in ('identical', 'ahead'):
        sys.exit(f'HEAD {head[:8]} is not on main on GitHub ({status or "unknown"}); push it first')
    if remote_tag(tag) or release_exists(tag):
        sys.exit(f'tag or release {tag} already exists on GitHub')
    if run('git', 'tag', '-l', tag).stdout.strip():
        sys.exit(f'local tag {tag} already exists')
    run('git', 'tag', tag, head)
    retry(lambda: push(f'refs/tags/{tag}'), lambda: remote_tag(tag) == head, f'pushing tag {tag}')
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile('w', suffix='.md', dir=ROOT / 'tmp', delete=False) as f:
        f.write(notes)
    try:
        create = ['gh', 'release', 'create', tag, '-R', GH_REPO, '--verify-tag',
                  '--title', title, '--notes-file', f.name] + (['--prerelease'] if prerelease else [])
        retry(lambda: run(*create, check=False), lambda: release_exists(tag), f'creating release {tag}')
    finally:
        os.unlink(f.name)
    retry(lambda: run('gh', 'release', 'upload', tag, '-R', GH_REPO, '--clobber',
                      str(archive), str(digest), check=False),
          lambda: asset_count(tag) == 2, f'uploading to {tag}')
    with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as d:
        retry(lambda: run('gh', 'release', 'download', tag, '-R', GH_REPO, '-p', archive.name,
                          '-D', d, '--clobber', check=False),
              lambda: (Path(d) / archive.name).is_file(), f'downloading {archive.name}')
        got = hashlib.sha256((Path(d) / archive.name).read_bytes()).hexdigest()
    if got != digest.read_text().split()[0]:
        sys.exit(f'the published {archive.name} differs from {digest.name}')
    print(f'released {RELEASES}{tag}')


if __name__ == '__main__':
    main()
