import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_deploy as deploy

IMAGE = 'ghcr.io/example/home-movies@sha256:' + 'a' * 64
SETTINGS = {'hostname': 'movies.example.com', 'image_repository': 'ghcr.io/example/home-movies'}


class DeploymentTests(unittest.TestCase):
    def test_only_exact_repository_and_sha256_are_accepted(self):
        self.assertEqual(deploy.validate_image(IMAGE, SETTINGS['image_repository']), IMAGE)
        for image in ('ghcr.io/other/movies@sha256:' + 'a' * 64, 'ghcr.io/example/home-movies:latest',
                      IMAGE + ';id', IMAGE + '\n', IMAGE[:-1], 'https://' + IMAGE):
            with self.assertRaises(deploy.DeployError):
                deploy.validate_image(image, SETTINGS['image_repository'])
        with self.assertRaises(deploy.DeployError):
            deploy.validate_image(IMAGE, 'ghcr.io/example/home-movies;id')

    def test_settings_require_root_ownership_no_other_writers_and_safe_hostname(self):
        config = Mock()
        config.stat.return_value = SimpleNamespace(st_uid=0, st_mode=0o644)
        config.read_text.return_value = '{"hostname":"movies.example.com"}'
        with patch.object(deploy, 'CONFIG', config):
            self.assertEqual(deploy.load_settings()['hostname'], SETTINGS['hostname'])
            for uid, mode in ((10001, 0o644), (0, 0o664), (0, 0o666)):
                config.stat.return_value = SimpleNamespace(st_uid=uid, st_mode=mode)
                with self.assertRaises(deploy.DeployError):
                    deploy.load_settings()
            config.stat.return_value = SimpleNamespace(st_uid=0, st_mode=0o644)
            config.read_text.return_value = '{"hostname":"bad;id"}'
            with self.assertRaises(deploy.DeployError):
                deploy.load_settings()

    def test_host_commands_do_not_use_shell_or_expose_output(self):
        with patch.object(deploy.subprocess, 'run') as run:
            deploy.command(['podman', 'pull', IMAGE])
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs['stderr'], deploy.subprocess.DEVNULL)
            run.side_effect = RuntimeError('<private-error>')
            with self.assertRaises(deploy.DeployError) as caught:
                deploy.command(['podman'])
            self.assertNotIn('<private-error>', str(caught.exception))

    def test_image_record_is_atomic_owner_only_and_cleans_failed_temporary_write(self):
        with tempfile.TemporaryDirectory() as root:
            image_file = Path(root) / 'image.env'
            with patch.object(deploy, 'IMAGE_FILE', image_file):
                deploy.record_image(IMAGE)
                self.assertEqual(image_file.read_text(), 'IMAGE=' + IMAGE + '\n')
                self.assertEqual(image_file.stat().st_mode & 0o777, 0o600)
                with patch.object(deploy.os, 'replace', side_effect=OSError('synthetic')):
                    with self.assertRaises(OSError):
                        deploy.record_image(IMAGE)
                self.assertEqual(list(Path(root).iterdir()), [image_file])

    def test_health_check_is_local_host_bound_and_fails_closed(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        with patch.object(deploy.urllib.request, 'build_opener', return_value=opener):
            for status in (200, 401, 503):
                response.status = status
                self.assertEqual(deploy.healthy(SETTINGS['hostname']), status == 200)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:5000/health')
            self.assertEqual(request.get_header('Host'), 'movies.example.com')
            opener.open.side_effect = OSError('synthetic')
            self.assertFalse(deploy.healthy(SETTINGS['hostname']))

    def test_pull_precedes_service_change_and_health_failure_is_reported(self):
        for result in (True, False):
            with tempfile.TemporaryDirectory() as root, patch.object(deploy, 'LOCK', Path(root) / 'lock'), \
                    patch.object(deploy, 'command') as command, patch.object(deploy, 'record_image') as record, \
                    patch.object(deploy, 'healthy', return_value=result) as healthy, patch.object(deploy.time, 'sleep'):
                order = Mock(); order.attach_mock(command, 'command'); order.attach_mock(record, 'record')
                if result:
                    deploy.deploy(IMAGE, SETTINGS)
                else:
                    with self.assertRaises(deploy.DeployError):
                        deploy.deploy(IMAGE, SETTINGS)
                    self.assertEqual(healthy.call_count, 30)
                self.assertEqual(order.mock_calls[0].args[0], ['/usr/bin/podman', 'pull', IMAGE])
                self.assertEqual(order.mock_calls[1].args[0], IMAGE)
                self.assertEqual(order.mock_calls[2].args[0], ['/usr/bin/systemctl', 'restart', 'home-movies.service'])

    def test_failed_pull_and_concurrent_deploy_do_not_change_running_service(self):
        with tempfile.TemporaryDirectory() as root, patch.object(deploy, 'LOCK', Path(root) / 'lock'), \
                patch.object(deploy, 'command', side_effect=deploy.DeployError('failed')), patch.object(deploy, 'record_image') as record:
            with self.assertRaises(deploy.DeployError):
                deploy.deploy(IMAGE, SETTINGS)
            record.assert_not_called()
            with patch.object(deploy.fcntl, 'flock', side_effect=BlockingIOError()):
                with self.assertRaises(deploy.DeployError):
                    deploy.deploy(IMAGE, SETTINGS)
            record.assert_not_called()

    def test_entrypoint_requires_root_and_one_argument_and_sanitizes_errors(self):
        with patch.object(deploy.os, 'geteuid', return_value=0), patch.object(sys, 'argv', ['helper', IMAGE]), \
                patch.object(deploy, 'load_settings', return_value=SETTINGS), patch.object(deploy, 'deploy') as invoke, patch('builtins.print'):
            self.assertEqual(deploy.main(), 0); invoke.assert_called_once_with(IMAGE, SETTINGS)
            invoke.side_effect = RuntimeError('<private-error>')
            self.assertEqual(deploy.main(), 1)
        for uid, args in ((10001, ['helper', IMAGE]), (0, ['helper']), (0, ['helper', IMAGE, 'extra'])):
            with patch.object(deploy.os, 'geteuid', return_value=uid), patch.object(sys, 'argv', args), \
                    patch.object(deploy, 'deploy') as invoke, patch('builtins.print'):
                self.assertEqual(deploy.main(), 1); invoke.assert_not_called()
