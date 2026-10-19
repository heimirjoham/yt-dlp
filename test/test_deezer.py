import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp.downloader.deezer import DeezerFD
from yt_dlp.extractor.deezer import DeezerSearchIE, DeezerTrackIE
from yt_dlp.networking import Request
from yt_dlp.utils import ExtractorError


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


class TestDeezerSearch(unittest.TestCase):
    def test_search_results_follow_pagination(self):
        ie = DeezerSearchIE(None)

        def track_edge(track_id, title, artist):
            return {'node': {
                'id': str(track_id),
                'title': title,
                'contributors': {'edges': [{'node': {'name': artist}}]},
            }}

        first_page = {
            'data': {'instantSearch': {'results': {'tracks': {
                'edges': [track_edge(track_id, 'Popular TEST track', 'Query artist') for track_id in range(1, 6)]
                    + [track_edge(6, 'Popular unrelated track', 'Other artist')],
                'pageInfo': {'endCursor': '6'},
            }}}},
        }
        second_page = {
            'data': {'instantSearch': {'results': {'tracks': {
                'edges': [track_edge(7, 'Query then test', 'Artist')],
                'pageInfo': {'endCursor': '7'},
            }}}},
        }
        responses = [{'jwt': 'test-bearer-token'}, first_page, second_page]
        with patch.object(ie, '_download_json', side_effect=responses) as download_json:
            results = list(ie._search_results('test-query'))

        self.assertEqual([result['url'] for result in results], [
            *[f'https://www.deezer.com/track/{track_id}' for track_id in range(1, 6)],
            'https://www.deezer.com/track/7',
        ])
        self.assertTrue(all(result['ie_key'] == 'DeezerTrack' for result in results))
        auth_call = download_json.call_args_list[0]
        self.assertEqual(auth_call.args[0], ie._AUTH_URL)
        self.assertEqual(auth_call.kwargs['data'], b'')
        self.assertEqual(auth_call.kwargs['headers']['Origin'], 'https://www.deezer.com')
        search_calls = download_json.call_args_list[1:]
        first_payload = json.loads(search_calls[0].kwargs['data'])
        second_payload = json.loads(search_calls[1].kwargs['data'])
        self.assertEqual(search_calls[0].args[0], ie._API_URL)
        self.assertEqual(first_payload['operationName'], 'SearchFull')
        self.assertIn('contributors', first_payload['query'])
        self.assertEqual(first_payload['variables'], {
            'query': 'test-query', 'firstList': 6, 'after': None,
        })
        self.assertEqual(second_payload['variables']['after'], '6')
        self.assertEqual(search_calls[0].kwargs['headers']['Authorization'], 'Bearer test-bearer-token')
        self.assertEqual(search_calls[0].kwargs['headers']['Cookie'], '')

    def test_search_requires_bearer_token(self):
        ie = DeezerSearchIE(None)
        with patch.object(ie, '_download_json', return_value={}):
            with self.assertRaisesRegex(ExtractorError, 'Unable to obtain a Deezer bearer token'):
                list(ie._search_results('test query'))


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
