"""R2 service boundary for private owner-scoped media.

Pass an S3-compatible SDK client configured with the account's R2 endpoint.
Persist asset IDs, owner IDs and reserved sizes before signing browser uploads.
"""
import os
import re
from uuid import UUID

MEDIA_TYPES = {'video/mp4', 'video/quicktime', 'video/webm'}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class PrivateMedia:
    def __init__(self, s3, bucket):
        self.s3 = s3
        self.bucket = bucket
        self.origin = None

    @classmethod
    def configured(cls):
        keys = ('ACCOUNT_ID', 'BUCKET', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY')
        values = [os.environ.get('CLIPFLOW_R2_' + key, '') for key in keys]
        if not any(values):
            return None
        if not all(values) or not re.fullmatch(r'[0-9a-f]{32}', values[0]):
            raise ValueError('Configure a valid R2 account ID, bucket and scoped credentials')
        import boto3
        from botocore.config import Config

        account, bucket, access, secret = values
        origin = f'https://{account}.r2.cloudflarestorage.com'
        config = Config(signature_version='s3v4', connect_timeout=5, read_timeout=15,
                        retries={'total_max_attempts': 2}, s3={'addressing_style': 'path'},
                        request_checksum_calculation='when_required',
                        response_checksum_validation='when_required')
        store = cls(boto3.client('s3', region_name='auto', endpoint_url=origin, config=config,
                                 aws_access_key_id=access, aws_secret_access_key=secret), bucket)
        store.origin = origin
        return store

    def _object(self, owner_id, asset_id, variant):
        return {'Bucket': self.bucket,
                'Key': f'owners/{UUID(str(owner_id)).hex}/{UUID(str(asset_id)).hex}/{variant}'}

    def sign_upload(self, owner_id, asset_id, *, mime, size):
        if mime not in MEDIA_TYPES or type(size) is not int or not 0 < size <= MAX_UPLOAD_BYTES:
            raise ValueError('Select a supported video within the upload limit')
        params = self._object(owner_id, asset_id, 'source')
        params.update(ContentType=mime, ContentLength=size)
        url = self.s3.generate_presigned_url('put_object', Params=params, ExpiresIn=300)
        return {'url': url, 'headers': {'Content-Type': mime}}

    def verify_upload(self, owner_id, asset_id, *, mime, size):
        if mime not in MEDIA_TYPES or type(size) is not int or not 0 < size <= MAX_UPLOAD_BYTES:
            raise ValueError('Invalid asset reservation')
        obj = self._object(owner_id, asset_id, 'source')
        found = self.s3.head_object(**obj)
        if found['ContentLength'] != size or found['ContentType'] != mime:
            raise ValueError('Uploaded object does not match the reservation')
        return found['ETag']

    def stage_source(self, owner_id, asset_id, *, etag, size, destination):
        obj = self._object(owner_id, asset_id, 'source')
        result = self.s3.get_object(**obj, IfMatch=etag)
        body = result['Body']
        try:
            if result['ContentLength'] != size:
                raise ValueError('Source size does not match upload reservation')
            with destination.open('xb') as output:
                remaining = size
                while remaining:
                    chunk = body.read(min(remaining, 65536))
                    if not chunk:
                        raise OSError('Incomplete R2 source')
                    output.write(chunk)
                    remaining -= len(chunk)
        finally:
            body.close()

    def save_output(self, owner_id, asset_id, revision, source):
        obj = self._object(owner_id, asset_id, self._output_key(revision))
        with source.open('rb') as body:
            self.s3.put_object(**obj, Body=body, ContentType='video/mp4')

    def drop_source(self, owner_id, asset_id):
        self.s3.delete_object(**self._object(owner_id, asset_id, 'source'))

    def drop_output(self, owner_id, asset_id, revision):
        self.s3.delete_object(**self._object(owner_id, asset_id, self._output_key(revision)))

    @staticmethod
    def _output_key(revision):
        return 'output.mp4' if revision is None else f'{UUID(str(revision)).hex}.mp4'

    def sign_preview(self, owner_id, asset_id, *, download=False, revision=None):
        params = self._object(owner_id, asset_id, self._output_key(revision))
        if download:
            params['ResponseContentDisposition'] = 'attachment; filename="clipflow.mp4"'
        return self.s3.generate_presigned_url('get_object', Params=params, ExpiresIn=300)
