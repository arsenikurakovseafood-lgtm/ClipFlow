import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipflow.youtube import ImportFailed, fetch_youtube, youtube_url


class YouTubeTests(unittest.TestCase):
    def test_only_single_video_links_are_accepted(self):
        expected = 'https://www.youtube.com/watch?v=M7lc1UVf-VE'
        for link in ['https://youtu.be/M7lc1UVf-VE?si=tracking',
                     'https://www.youtube.com/shorts/M7lc1UVf-VE',
                     expected + '&list=other']:
            self.assertEqual(youtube_url(link), expected)
        for link in ['https://youtube.com/playlist?list=abc', 'http://youtu.be/M7lc1UVf-VE',
                     'https://youtube.com@other.example/watch?v=M7lc1UVf-VE',
                     'https://www.youtube.com:443/watch?v=M7lc1UVf-VE']:
            self.assertIsNone(youtube_url(link))

    def test_download_writes_only_staged_source_and_hides_provider_details(self):
        url = 'https://youtu.be/M7lc1UVf-VE'
        with tempfile.TemporaryDirectory() as work:
            destination = Path(work) / 'source'

            def downloaded(args, **kwargs):
                Path(args[args.index('--output') + 1]).write_bytes(b'media test fixture')
                self.assertEqual(kwargs['timeout'], 65)
                self.assertIn('--no-playlist', args)
                self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
                return subprocess.CompletedProcess(args, 0, '', '')

            with patch('clipflow.youtube.subprocess.run', side_effect=downloaded):
                fetch_youtube(url, destination)
            self.assertEqual(destination.read_bytes(), b'media test fixture')
            self.assertEqual(list(Path(work).iterdir()), [destination])

            failure = subprocess.CompletedProcess([], 1, '', 'ERROR: Sign in to confirm')
            with patch('clipflow.youtube.subprocess.run', return_value=failure):
                with self.assertRaisesRegex(ImportFailed, 'refused access'):
                    fetch_youtube(url, destination)
