#!/usr/bin/python3
"""Root-owned Run Command entry point. Accept only the configured repository/digest."""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CONFIG = Path('/etc/home-movies/deploy.json')
IMAGE_FILE = Path('/etc/home-movies/image.env')
LOCK = Path('/run/home-movies-deploy.lock')


class DeployError(Exception):
    pass


def validate_image(image, repository):
    if not re.fullmatch(r'ghcr\.io/[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*', repository):
        raise DeployError('Invalid configured image repository.')
    if not re.fullmatch(re.escape(repository) + r'@sha256:[a-f0-9]{64}', image):
        raise DeployError('Supply a digest from the configured image repository.')
    return image


def load_settings():
    stat = CONFIG.stat()
    if stat.st_uid != 0 or stat.st_mode & 0o022:
        raise DeployError('Deployment configuration must be root-owned and not writable by others.')
    settings = json.loads(CONFIG.read_text())
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]+[a-zA-Z0-9]', settings['hostname']):
        raise DeployError('Invalid health-check hostname.')
    return settings


def command(arguments):
    try:
        subprocess.run(arguments, check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        raise DeployError('Host operation failed; raw details suppressed.') from None


def record_image(image):
    # Atomically replace the service's digest after the image has been pulled.
    descriptor, name = tempfile.mkstemp(prefix='.image-', dir=IMAGE_FILE.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write('IMAGE=' + image + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, IMAGE_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def healthy(hostname):
    request = urllib.request.Request('http://127.0.0.1:5000/health', headers={'Host': hostname})
    # Never send local health checks through an environment-supplied HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def deploy(image, settings):
    image = validate_image(image, settings['image_repository'])
    with open(LOCK, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeployError('Another deployment is in progress.') from None
        command(['/usr/bin/podman', 'pull', image])
        record_image(image)
        command(['/usr/bin/systemctl', 'restart', 'home-movies.service'])
        for attempt in range(30):
            if healthy(settings['hostname']):
                return
            time.sleep(2)
        raise DeployError('Application did not become healthy after deployment.')


def main():
    try:
        if os.geteuid() != 0 or len(sys.argv) != 2:
            raise DeployError('Run the installed helper as root with one image digest.')
        deploy(sys.argv[1], load_settings())
        print('Home Movies deployment passed the local health check.')
        return 0
    except Exception:
        print('Home Movies deployment failed; raw details suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
