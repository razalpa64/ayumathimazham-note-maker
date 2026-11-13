import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image

from app import analyze_pdf, process_one


class FixedWatermarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'source.pdf'
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 60), 'Important notes', fontsize=12)
        buf = io.BytesIO()
        Image.new('RGB', (20, 20), 'red').save(buf, format='PNG')
        self.xref = page.insert_image(fitz.Rect(20, 20, 40, 40), stream=buf.getvalue())
        doc.save(self.path)
        doc.close()
        self.info = {'path': str(self.path), 'filename': 'source.pdf', 'page_count': 1}
        self.job = {'id': 'test', 'download_dir': self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def process(self, config):
        with patch('app.add_cover', side_effect=lambda output, fields, logo: output.new_page()):
            return process_one(self.job, self.info, config)

    def test_separate_single_page_image_can_be_removed_without_notes(self):
        analysis = analyze_pdf(self.path, 'doc', 'source.pdf')
        self.assertIn(self.xref, [i['xref'] for i in analysis['repeated_images']])
        result = self.process({'remove_images': [self.xref], 'watermark': False})
        self.assertTrue(result['ok'], result)
        out = fitz.open(Path(self.tmp.name) / result['filename'])
        self.assertIn('Important notes', out[1].get_text())
        pix = out[1].get_pixmap(alpha=False)
        self.assertEqual(pix.pixel(25, 25)[:3], (255, 255, 255))
        out.close()

    def test_no_automatic_text_or_link_removal(self):
        doc = fitz.open(self.path)
        doc[0].insert_text((20, 90), 'Visit www.example.com')
        doc.save(Path(self.tmp.name) / 'new.pdf')
        doc.close()
        self.info['path'] = str(Path(self.tmp.name) / 'new.pdf')
        result = self.process({'watermark': False})
        self.assertTrue(result['ok'], result)
        out = fitz.open(Path(self.tmp.name) / result['filename'])
        self.assertIn('www.example.com', out[1].get_text())
        out.close()

    def test_legacy_area_redaction_fails_closed(self):
        result = self.process({'erase_regions': [{'x0': 0, 'y0': 0, 'x1': 1, 'y1': 1, 'page': None}]})
        self.assertFalse(result['ok'])
        self.assertIn('disabled', result['error'])

    def test_full_page_scan_not_suggested(self):
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        buf = io.BytesIO(); Image.new('RGB', (50, 50), 'black').save(buf, format='PNG')
        page.insert_image(page.rect, stream=buf.getvalue())
        path = Path(self.tmp.name) / 'scan.pdf'; doc.save(path); doc.close()
        analysis = analyze_pdf(path, 'doc', 'scan.pdf')
        self.assertEqual(analysis['repeated_images'], [])


if __name__ == '__main__':
    unittest.main()
