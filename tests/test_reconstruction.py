import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image, ImageDraw

import app as application


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'scan.pdf'
        image = Image.new('RGB', (200, 200), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((25, 25, 40, 40), fill=(200, 200, 200))
        draw.rectangle((100, 100, 120, 120), fill=(0, 0, 0))
        data = io.BytesIO(); image.save(data, format='PNG')
        doc = fitz.open(); page = doc.new_page(width=200, height=200)
        page.insert_image(page.rect, stream=data.getvalue())
        doc.save(self.path); doc.close()
        self.settings = dict(x0=.10, y0=.10, x1=.25, y1=.25, color='#c8c8c8', tolerance=3, page=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_inpaint_changes_only_selected_color(self):
        with fitz.open(self.path) as doc:
            result = Image.open(io.BytesIO(application.reconstruct_scan(doc[0], self.settings)))
            self.assertGreater(result.getpixel((60, 60))[0], 200)
            self.assertEqual(result.getpixel((220, 220)), (0, 0, 0))

    def test_mixed_page_rejected(self):
        doc = fitz.open(self.path); page = doc[0]; page.insert_text((10, 180), 'Notes')
        with self.assertRaisesRegex(ValueError, 'limited to pages'):
            application.reconstruct_scan(page, self.settings)
        doc.close()

    def test_approval_and_output(self):
        job = {'id': 'test', 'download_dir': self.temp.name}
        info = {'path': str(self.path), 'filename': 'scan.pdf', 'page_count': 1}
        with patch('app.add_cover', side_effect=lambda out, fields, logo: out.new_page()):
            denied = application.process_one(job, info, {'scan_reconstruction': self.settings})
            self.assertFalse(denied['ok'])
            result = application.process_one(job, info, {'watermark': False, 'scan_reconstruction': {**self.settings, 'approved': True}})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['reconstructed_page'], 1)
        with fitz.open(Path(self.temp.name) / result['filename']) as doc:
            self.assertGreater(doc[1].get_pixmap().pixel(30,30)[0], 200)
            self.assertEqual(doc[1].get_pixmap().pixel(110,110)[:3], (0,0,0))
        with fitz.open(self.path) as original:
            self.assertEqual(original[0].get_pixmap().pixel(30,30)[:3], (200,200,200))

    def test_invalid_settings_and_no_match(self):
        with fitz.open(self.path) as doc:
            with self.assertRaises(ValueError):
                application.reconstruct_scan(doc[0], {**self.settings, 'x0': float('nan')})
            with self.assertRaisesRegex(ValueError, 'No pixels'):
                application.reconstruct_scan(doc[0], {**self.settings, 'color': '#ff0000'})

    def test_preview_endpoint(self):
        job = {'files': {'doc': {'path': str(self.path)}}}
        with patch('app.get_job_state', return_value=job):
            response = application.app.test_client().post('/api/reconstruct-preview/job/doc/0', json=self.settings)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/png')


if __name__ == '__main__':
    unittest.main()
