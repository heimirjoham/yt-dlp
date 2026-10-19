import io
import os
import tempfile
import unittest
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp.downloader.deezer import DeezerFD
from yt_dlp.extractor.deezer import DeezerTrackIE
from yt_dlp.networking import Request


class TestDeezerDownloader(unittest.TestCase):
    def test_uses_networking_request_and_response_headers(self):
        class Response(io.BytesIO):
            headers = {'Content-length': '5'}

        ydl = YoutubeDL({'quiet': True})
        response = Response(b'audio')
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, 'audio')
            with patch.object(ydl, 'urlopen', return_value=response) as urlopen:
                downloader = DeezerFD(ydl, {'quiet': True})
                self.assertTrue(downloader.real_download(filename, {'url': 'https://example.test/audio'}))

            self.assertIsInstance(urlopen.call_args.args[0], Request)
            with open(filename, 'rb') as audio_file:
                self.assertEqual(audio_file.read(), b'audio')


class TestDeezerExtractor(unittest.TestCase):
    def test_audio_format_selectable_as_bestaudio(self):
        ie = DeezerTrackIE(None)
        track = {
            'FILESIZE_MP3_128': '100',
            'TRACK_TOKEN': 'token',
            'MEDIA': [{'HREF': 'https://example.test/audio'}],
            'SNG_ID': '123',
            'DURATION': '10',
            'DIGITAL_RELEASE_DATE': '20200101',
        }
        get_url_response = {
            'data': [{
                'media': [{
                    'sources': [{'provider': 'akg', 'url': 'https://example.test/audio'}],
                }],
            }],
        }

        with (
            patch.object(ie, 'get_api_license_tokens', return_value=('api', 'license')),
            patch.object(ie, '_download_json', side_effect=[{'results': {'data': [track]}}, get_url_response]),
            patch.object(ie, 'get_key_dynamically'),
            patch.object(ie, 'compute_blowfish_key', return_value='key'),
        ):
            entries = ie.get_entries('123', {}, {})

        ydl = YoutubeDL({'quiet': True})
        selected = ydl._select_formats(entries[0]['formats'], ydl.build_format_selector('bestaudio'))
        self.assertEqual([f['format_id'] for f in selected], ['MP3_128'])
