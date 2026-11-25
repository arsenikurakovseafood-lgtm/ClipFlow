import unittest
from unittest.mock import Mock
from uuid import uuid4

from clipflow.r2 import PrivateMedia


class R2Tests(unittest.TestCase):
    def test_scope_upload_and_explicit_download(self):
        sdk = Mock()
        sdk.generate_presigned_url.return_value = 'https://invalid.example/signed-fixture'
        media = PrivateMedia(sdk, 'private')
        owner, asset = uuid4(), uuid4()
        with self.assertRaises(ValueError):
            media.sign_upload(owner, asset, mime='text/html', size=12)
        sdk.generate_presigned_url.assert_not_called()
        media.sign_upload(owner, asset, mime='video/mp4', size=12)
        operation, = sdk.generate_presigned_url.call_args.args
        params = sdk.generate_presigned_url.call_args.kwargs['Params']
        self.assertEqual(operation, 'put_object')
        self.assertEqual(params['ContentLength'], 12)
        self.assertEqual(params['ContentType'], 'video/mp4')
        self.assertEqual(params['Key'], f'owners/{owner.hex}/{asset.hex}/source')
        sdk.head_object.return_value = {'ContentLength': 13, 'ContentType': 'video/mp4', 'ETag': 'fixture'}
        with self.assertRaises(ValueError):
            media.verify_upload(owner, asset, mime='video/mp4', size=12)
        media.sign_preview(owner, asset)
        self.assertNotIn('ResponseContentDisposition', sdk.generate_presigned_url.call_args.kwargs['Params'])
        media.sign_preview(owner, asset, download=True)
        self.assertIn('attachment', sdk.generate_presigned_url.call_args.kwargs['Params']['ResponseContentDisposition'])
