"""R2 service boundary for private owner-scoped media.

Pass an S3-compatible SDK client configured with the account's R2 endpoint.
Persist asset IDs, owner IDs and reserved sizes before signing browser uploads.
"""
from uuid import UUID

MEDIA_TYPES = {'video/mp4', 'video/quicktime', 'video/webm'}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class PrivateMedia:
    def __init__(self, s3, bucket):
        self.s3 = s3
        self.bucket = bucket

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

    def sign_preview(self, owner_id, asset_id, *, download=False):
        params = self._object(owner_id, asset_id, 'output.mp4')
        if download:
            params['ResponseContentDisposition'] = 'attachment; filename="clipflow.mp4"'
        return self.s3.generate_presigned_url('get_object', Params=params, ExpiresIn=300)
