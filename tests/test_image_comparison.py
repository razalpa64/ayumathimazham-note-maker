import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image
import app


def png(color, mode='RGB'):
    data = io.BytesIO()
    Image.new(mode, (20, 20), color).save(data, format='PNG')
    return data.getvalue()


class ImageComparisonTests(unittest.TestCase):
    def test_comparison_removes_image_but_leaves_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pdf'
            doc = fitz.open(); p = doc.new_page(width=200, height=200)
            p.insert_text((15, 30), 'Unchanged text')
            xref = p.insert_image(fitz.Rect(50, 50, 100, 100), stream=png('red'))
            doc.save(path); doc.close()
            job = {'files': {'doc': {'path': str(path)}}}
            with patch('app.get_job_state', return_value=job):
                client = app.app.test_client()
                response = client.get(f'/image-removal-preview/job/doc/{xref}/0')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/png')
                image = Image.open(io.BytesIO(response.data))
                # preview is scaled to .65
                self.assertEqual(image.getpixel((40, 40)), (255, 255, 255))
                self.assertEqual(client.get(f'/image-removal-preview/job/doc/{xref}/1').status_code, 404)
            with fitz.open(path) as original:
                self.assertEqual(original[0].get_pixmap().pixel(60, 60)[:3], (255, 0, 0))

    def test_failed_text_verification_stops_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pdf'
            doc = fitz.open(); page = doc.new_page(width=200, height=200)
            page.insert_text((10, 30), 'Important text')
            xref = page.insert_image(fitz.Rect(50, 50, 70, 70), stream=png('red'))
            doc.save(path); doc.close()
            with patch.object(fitz.Page, 'get_text', side_effect=['original', 'changed']):
                result = app.process_one({'id': 'test', 'download_dir': tmp},
                    {'path': str(path), 'filename': 'source.pdf', 'page_count': 1},
                    {'add_cover': False, 'watermark': False, 'remove_image_groups': [xref]})
            self.assertFalse(result['ok'])
            self.assertIn('Text changed', result['error'])
            self.assertEqual(sorted(p.name for p in Path(tmp).glob('*.pdf')), ['source.pdf'])

    def test_shared_mask_is_never_suggested_or_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pdf'
            doc = fitz.open(); page = doc.new_page(width=200, height=200)
            mask = page.insert_image(fitz.Rect(10, 10, 30, 30), stream=png(128, 'L'))
            image = page.insert_image(fitz.Rect(50, 50, 70, 70), stream=png('red'))
            doc.xref_set_key(image, 'SMask', f'{mask} 0 R')
            doc.save(path); doc.close()
            analysis = app.analyze_pdf(path, 'doc', 'source.pdf')
            self.assertNotIn(mask, [x['xref'] for x in analysis['repeated_images']])
            result = app.process_one({'id': 'test', 'download_dir': tmp},
                {'path': str(path), 'filename': 'source.pdf', 'page_count': 1},
                {'add_cover': False, 'remove_image_groups': [mask]})
            self.assertFalse(result['ok'])
            self.assertIn('mask', result['error'])
            with patch('app.get_job_state', return_value={'files': {'doc': {'path': str(path)}}}):
                response = app.app.test_client().get(f'/image-removal-preview/job/doc/{mask}/0')
            self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
