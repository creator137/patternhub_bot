from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from fastapi.testclient import TestClient
from app.database import Database
from app.services.miniapp_branding import MAX_AVATAR_BYTES
from app.web.main import create_app
from app.web.auth import WebSettings
from test_web import signed


def picture(color='green'):
    out=BytesIO();Image.new('RGB',(720,480),color).save(out,format='PNG');return out.getvalue()


class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'catalog.sqlite3')
        self.client=TestClient(create_app(self.db,WebSettings('test-token',frozenset({42}))))
        self.addCleanup(self.client.close)
        self.auth={'X-Telegram-Init-Data':signed()}

    def upload(self,data):
        return self.client.put('/api/admin/branding/avatar',headers=self.auth,content=data)

    def test_upload_persists_square_logo_with_versioned_public_url(self):
        self.assertEqual(self.client.get('/api/meta').json()['avatar_url'],'/brand/avatar.jpg')
        r=self.upload(picture());self.assertEqual(r.status_code,200)
        url=r.json()['avatar_url'];self.assertTrue(url.startswith('/api/branding/avatar/'))
        self.db.initialize()
        self.assertEqual(self.client.get('/api/meta').json()['avatar_url'],url)
        response=self.client.get(url);self.assertEqual(response.status_code,200)
        self.assertIn('immutable',response.headers['cache-control'])
        with Image.open(BytesIO(response.content)) as img:
            self.assertEqual(img.size,(256,256));self.assertEqual(img.format,'WEBP')
        newer=self.upload(picture('blue')).json()['avatar_url']
        self.assertNotEqual(newer,url)
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(newer).status_code,200)

    def test_only_admin_can_upload_and_no_file_written_for_unauthorized_request(self):
        for headers,status in [({},401),({'X-Telegram-Init-Data':signed(99)},403)]:
            r=self.client.put('/api/admin/branding/avatar',headers=headers,content=picture())
            self.assertEqual(r.status_code,status)
        self.assertFalse((self.db.path.parent/'branding').exists())

    def test_bad_file_and_oversize_do_not_replace_saved_avatar(self):
        url=self.upload(picture()).json()['avatar_url']
        for data in [b'',b'not-an-image',b'<svg xmlns="http://www.w3.org/2000/svg"></svg>']:
            self.assertEqual(self.upload(data).status_code,422)
        self.assertEqual(self.upload(b'x'*(MAX_AVATAR_BYTES+1)).status_code,413)
        self.assertEqual(self.client.get('/api/meta').json()['avatar_url'],url)
        self.assertEqual(self.client.get('/api/branding/avatar/not-a-key.webp').status_code,404)

    def test_image_metadata_is_not_published(self):
        out=BytesIO();img=Image.new('RGB',(100,100),'red');exif=Image.Exif();exif[315]='private-test-metadata';img.save(out,format='JPEG',exif=exif)
        url=self.upload(out.getvalue()).json()['avatar_url'];data=self.client.get(url).content
        self.assertNotIn(b'private-test-metadata',data)
        with Image.open(BytesIO(data)) as sanitized:self.assertFalse(sanitized.getexif())
