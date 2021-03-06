from io import BytesIO
from unittest import TestCase
from eve.io.media import MediaStorage
from eve.io.mongo import GridFSMediaStorage
from eve.tests import TestBase, MONGO_DBNAME
from eve import STATUS_OK, ID_FIELD, STATUS, STATUS_ERR, ISSUES, ETAG
import base64
from bson import ObjectId


class TestMediaStorage(TestCase):
    def test_base_media_storage(self):
        a = MediaStorage()
        self.assertEqual(a.app, None)

        a = MediaStorage("hello")
        self.assertEqual(a.app, "hello")

        self.assertRaises(NotImplementedError, a.get, 1)
        self.assertRaises(NotImplementedError, a.put, "clean", "filename")
        self.assertRaises(NotImplementedError, a.delete, 1)
        self.assertRaises(NotImplementedError, a.exists, 1)


class TestGridFSMediaStorage(TestBase):
    def setUp(self):
        super(TestGridFSMediaStorage, self).setUp()
        self.url = self.known_resource_url
        self.headers = [('Content-Type', 'multipart/form-data')]
        self.test_field, self.test_value = 'ref', "1234567890123456789054321"
        # we want an explicit binary as Py3 encodestring() expects binaries.
        self.clean = b'my file contents'
        # encodedstring will raise a DeprecationWarning under Python3.3, but
        # the alternative encodebytes is not available in Python 2.
        self.encoded = base64.encodestring(self.clean).decode('utf-8')

    def test_gridfs_media_storage_errors(self):
        self.assertRaises(TypeError, GridFSMediaStorage)
        self.assertRaises(TypeError, GridFSMediaStorage, "hello")

    def test_gridfs_media_storage_post(self):
        # send something different than a file and get an error back
        data = {'media': 'not a file'}
        r, s = self.parse_response(
            self.test_client.post(self.url, data=data, headers=self.headers))
        self.assertEqual(STATUS_ERR, r[STATUS])

        # validates media fields
        self.assertTrue('file was expected' in r[ISSUES]['media'])
        # also validates ordinary fields
        self.assertTrue('required' in r[ISSUES][self.test_field])

        r, s = self._post()
        self.assertEqual(STATUS_OK, r[STATUS])

        # compare original and returned data
        _id = r[ID_FIELD]
        self.assertMediaField(_id, self.encoded, self.clean)

        # GET the file at the resource endpoint
        where = 'where={"%s": "%s"}' % (ID_FIELD, _id)
        r, s = self.parse_response(
            self.test_client.get('%s?%s' % (self.url, where)))
        self.assertEqual(len(r['_items']), 1)
        returned = r['_items'][0]['media']

        # returned value is a base64 encoded string
        self.assertEqual(returned, self.encoded)

        # which decodes to the original clean
        self.assertEqual(base64.decodestring(returned.encode()), self.clean)

    def test_gridfs_media_storage_put(self):
        r, s = self._post()
        _id = r[ID_FIELD]
        etag = r[ETAG]

        # retrieve media_id and compare original and returned data
        media_id = self.assertMediaField(_id, self.encoded, self.clean)

        # PUT replaces the file with new one
        clean = b'my new file contents'
        encoded = base64.encodestring(clean).decode()
        test_field, test_value = 'ref', "9234567890123456789054321"
        data = {'media': (BytesIO(clean), 'test.txt'), test_field: test_value}
        headers = [('Content-Type', 'multipart/form-data'), ('If-Match', etag)]

        r, s = self.parse_response(
            self.test_client.put(('%s/%s' % (self.url, _id)), data=data,
                                 headers=headers))
        self.assertEqual(STATUS_OK, r[STATUS])

        # media has been properly stored
        self.assertMediaStored(_id)

        # compare original and returned data
        r, s = self.assertMediaField(_id, encoded, clean)

        # and of course, the ordinary field has been updated too
        self.assertEqual(r[test_field], test_value)

        # previous media doesn't exist anymore (it's been deleted)
        self.assertFalse(self.app.media.exists(media_id))

    def test_gridfs_media_storage_patch(self):
        r, s = self._post()
        _id = r[ID_FIELD]
        etag = r[ETAG]

        # retrieve media_id and compare original and returned data
        media_id = self.assertMediaField(_id, self.encoded, self.clean)

        # PATCH replaces the file with new one
        clean = b'my new file contents'
        encoded = base64.encodestring(clean).decode()
        test_field, test_value = 'ref', "9234567890123456789054321"
        data = {'media': (BytesIO(clean), 'test.txt'), test_field: test_value}
        headers = [('Content-Type', 'multipart/form-data'), ('If-Match', etag)]

        r, s = self.parse_response(
            self.test_client.patch(('%s/%s' % (self.url, _id)), data=data,
                                   headers=headers))
        self.assertEqual(STATUS_OK, r[STATUS])

        # compare original and returned data
        r, s = self.assertMediaField(_id, encoded, clean)

        # and of course, the ordinary field has been updated too
        self.assertEqual(r[test_field], test_value)

        # previous media doesn't exist anymore (it's been deleted)
        self.assertFalse(self.app.media.exists(media_id))

    def test_gridfs_media_storage_delete(self):
        r, s = self._post()
        _id = r[ID_FIELD]
        etag = r[ETAG]

        # retrieve media_id and compare original and returned data
        media_id = self.assertMediaField(_id, self.encoded, self.clean)

        # DELETE deletes both the document and the media file
        headers = [('If-Match', etag)]

        r, s = self.parse_response(
            self.test_client.delete(('%s/%s' % (self.url, _id)),
                                    headers=headers))
        self.assert200(s)

        # media doesn't exist anymore (it's been deleted)
        self.assertFalse(self.app.media.exists(media_id))

        # GET returns 404
        r, s = self.parse_response(self.test_client.get('%s/%s' % (self.url,
                                                                   _id)))
        self.assert404(s)

    def assertMediaField(self, _id, encoded, clean):
        # GET the file at the item endpoint
        r, s = self.parse_response(self.test_client.get('%s/%s' % (self.url,
                                                                   _id)))
        returned = r['media']
        # returned value is a base64 encoded string
        self.assertEqual(returned, encoded)
        # which decodes to the original file clean
        self.assertEqual(base64.decodestring(returned.encode()), clean)
        return r, s

    def assertMediaStored(self, _id):
        _db = self.connection[MONGO_DBNAME]

        # retrieve media id
        media_id = _db.contacts.find_one({ID_FIELD: ObjectId(_id)})['media']

        # verify it's actually stored in the media storage system
        self.assertTrue(self.app.media.exists(media_id))
        return media_id

    def _post(self):
        # send a file and a required, ordinary field with no issues
        data = {'media': (BytesIO(self.clean), 'test.txt'), self.test_field:
                self.test_value}
        return self.parse_response(self.test_client.post(
            self.url, data=data, headers=self.headers))
