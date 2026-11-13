import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image
import io

from app import process_one


class FixedRegionTests(unittest.TestCase):
    def test_flattened_image_and_page_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pdf'
            image = Image.new('RGB', (100, 100), 'black')
            buf = io.BytesIO()
            image.save(buf, format='PNG')
            doc = fitz.open()
            for _ in range(2):
                page = doc.new_page(width=100, height=100)
                page.insert_image(page.rect, stream=buf.getvalue())
            doc.save(path)
            doc.close()
            job = {'id': 'test', 'download_dir': tmp}
            info = {'path': str(path), 'filename': 'source.pdf', 'page_count': 2}
            config = {'watermark': False, 'erase_regions': [dict(x0=.1, y0=.1, x1=.3, y1=.3, page=0)]}
            with patch('app.add_cover', side_effect=lambda output, fields, logo: output.new_page()):
                result = process_one(job, info, config)
            self.assertTrue(result['ok'], result)
            out = fitz.open(Path(tmp) / result['filename'])
            def pixel(page, x, y):
                pix = page.get_pixmap(alpha=False)
                return pix.pixel(x, y)[:3]
            self.assertEqual(pixel(out[1], 20, 20), (255, 255, 255))
            self.assertEqual(pixel(out[1], 60, 60), (0, 0, 0))
            self.assertEqual(pixel(out[2], 20, 20), (0, 0, 0))
            out.close()

    def test_invalid_region_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pdf'
            doc = fitz.open(); doc.new_page(); doc.save(path); doc.close()
            result = process_one({'id': 'test', 'download_dir': tmp},
                                 {'path': str(path), 'filename': 'source.pdf', 'page_count': 1},
                                 {'erase_regions': [{'x0': -1, 'y0': 0, 'x1': 1, 'y1': 1, 'page': None}]})
            self.assertFalse(result['ok'])
            self.assertIn('Invalid fixed watermark region', result['error'])


if __name__ == '__main__':
    unittest.main()
