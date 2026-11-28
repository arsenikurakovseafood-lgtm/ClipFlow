import unittest

from clipflow.youtube import youtube_url


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
