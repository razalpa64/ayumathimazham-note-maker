import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image
import app


def image_stream(alpha):
    image = Image.new('RGBA', (20, 20), (200, 0, 0, alpha))
    data = io.BytesIO(); image.save(data, format='PNG')
    return data.getvalue()


class ImageGroupTests(unittest.TestCase):
    def test_distinct_xrefs_and_masks_group_without_losing_page_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.pdf'
            # Import one-page documents separately, creating separate image xrefs.
            doc = fitz.open()
            for alpha in (100, 100, 200):
                source = fitz.open(); page = source.new_page(width=200, height=200)
                page.insert_text((15, 30), 'Study content must remain')
                xref = page.insert_image(fitz.Rect(80, 80, 120, 120), stream=image_stream(alpha))
                source.xref_set_key(xref, 'ColorSpace', '/DeviceRGB')
                doc.insert_pdf(source); source.close()
            doc.set_metadata({'title': 'Original title', 'author': 'Original author'})
            doc.set_toc([[1, 'Chapter', 2]])
            doc.save(path); doc.close()
            analysis = app.analyze_pdf(path, 'doc', 'input.pdf')
            candidate = next(c for c in analysis['repeated_images'] if c['object_count'] == 2)
            self.assertEqual(candidate['pages'], [1, 2])
            with fitz.open(path) as original:
                self.assertNotEqual(app.image_fingerprint(original, original[0].get_images()[0][0]),
                                    app.image_fingerprint(original, original[2].get_images()[0][0]))
            with patch('app.add_cover', side_effect=AssertionError('cover must not be added')):
                result = app.process_one({'id': 'test', 'download_dir': tmp},
                    {'path': str(path), 'filename': 'input.pdf', 'page_count': 3},
                    {'add_cover': False, 'watermark': False, 'remove_image_groups': [candidate['xref']]})
            self.assertTrue(result['ok'], result)
            self.assertEqual(len(result['removed_images']), 2)
            with fitz.open(path) as original, fitz.open(Path(tmp) / result['filename']) as output:
                self.assertEqual(len(output), 3)
                self.assertEqual(original.metadata, output.metadata)
                self.assertEqual(original.get_toc(), output.get_toc())
                for i in range(3):
                    self.assertEqual(original[i].get_text(), output[i].get_text())
                self.assertEqual(output[0].get_pixmap().pixel(100, 100)[:3], (255, 255, 255))
                self.assertEqual(output[2].get_pixmap().pixel(100, 100), original[2].get_pixmap().pixel(100, 100))

    def test_mask_preview_contains_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.pdf'
            doc = fitz.open(); page = doc.new_page(); xref = page.insert_image(fitz.Rect(0, 0, 20, 20), stream=image_stream(100)); doc.save(path); doc.close()
            with patch('app.get_job_state', return_value={'files': {'doc': {'path': str(path)}}}):
                response = app.app.test_client().get(f'/image-preview/job/doc/{xref}')
            self.assertEqual(response.status_code, 200)
            image = Image.open(io.BytesIO(response.data))
            self.assertEqual(image.getpixel((1, 1))[3], 100)


if __name__ == '__main__':
    unittest.main()
