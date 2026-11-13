import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image
import app


class CoverWatermarkTests(unittest.TestCase):
    def test_cover_preview_uses_same_layout_as_pdf(self):
        layout = {'title_x': .7, 'title_y': .65, 'title_size': 28, 'logo_x': .35, 'logo_y': .25, 'logo_width': 190, 'title_color': '#2040aa'}
        fields = {'title': 'Test Subject', 'scheme': 'S3'}
        with patch('app.get_job_state', return_value={'files': {}}):
            response = app.app.test_client().post('/api/cover-preview/job', json={'fields': fields, 'cover_layout': layout})
        self.assertEqual(response.status_code, 200)
        with fitz.open() as doc:
            app.add_cover(doc, {**fields, '_cover_layout': layout}, None)
            image = doc[0].get_pixmap(matrix=fitz.Matrix(.7, .7), alpha=False).tobytes('png')
            self.assertEqual(response.data, image)
            rect = doc[0].search_for('Test Subject')[0]
            self.assertAlmostEqual((rect.x0 + rect.x1) / 2, .7 * 595, delta=2)

    def test_replace_cover_and_watermark_visible_on_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pdf'
            doc = fitz.open(); page = doc.new_page(width=595, height=842); page.insert_text((40, 40), 'OLD COVER')
            page = doc.new_page(width=595, height=842)
            buf = io.BytesIO(); Image.new('RGB', (595, 842), 'white').save(buf, 'PNG')
            page.insert_image(page.rect, stream=buf.getvalue()); doc.save(path); doc.close()
            config = {'fields': {'title': 'My Cover', 'watermark_text': 'MY WATERMARK', 'watermark_subtext': ' '}, 'add_cover': True,
                      'remove_pages': [0], 'watermark': True, 'watermark_pages': [1], 'watermark_position': 'top-left',
                      'cover_layout': {'title_x': .65, 'title_y': .68, 'title_size': 30}}
            result = app.process_one({'id': 'test', 'download_dir': tmp}, {'path':str(path), 'filename':'source.pdf', 'page_count':2}, config)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['removed_pages'], [1])
            with fitz.open(Path(tmp)/result['filename']) as out:
                self.assertEqual(len(out), 2)
                self.assertIn('My Cover', out[0].get_text())
                self.assertNotIn('OLD COVER', out[0].get_text())
                pix = out[1].get_pixmap(alpha=False)
                image = Image.frombytes('RGB', (pix.width,pix.height), pix.samples)
                self.assertIsNotNone(Image.eval(image.convert('L'), lambda p: 255-p).getbbox())
                bbox = Image.eval(image.convert('L'), lambda p: 255-p).getbbox()
                self.assertLess(bbox[2], 320)
                self.assertLess(bbox[3], 350)

    def test_image_watermark_position_and_opacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pdf'; art = Path(tmp) / 'stamp.png'
            Image.new('RGB', (100, 50), 'red').save(art)
            doc = fitz.open(); doc.new_page(width=595, height=842); doc.save(path); doc.close()
            result = app.process_one({'id': 'test', 'download_dir': tmp, 'watermark_image_path': str(art)},
                {'path': str(path), 'filename': 'source.pdf', 'page_count': 1},
                {'fields': {'watermark_type': 'image'}, 'add_cover': False, 'watermark': True,
                 'watermark_pages': [0], 'watermark_position': 'bottom-right'})
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['watermarked_pages'], [1])
            with fitz.open(Path(tmp) / result['filename']) as out:
                pix = out[0].get_pixmap(alpha=False)
                rgb = pix.pixel(round(595 * .75), round(842 * .8))
                self.assertGreater(rgb[0], 240)
                self.assertGreater(rgb[1], 180)
                self.assertLess(rgb[1], 255)
                self.assertEqual(pix.pixel(30, 30)[:3], (255, 255, 255))

    def test_position_text_alpha_bounds(self):
        bboxes=[]
        for position in (app.WATERMARK_POSITIONS['top-left'], app.WATERMARK_POSITIONS['bottom-right']):
            png=app.render_text_watermark_png(595,842,'HELLO','',(.6,.6,.6),app.BASE/'static'/'NotoSansMalayalam.ttf',position)
            bboxes.append(Image.open(io.BytesIO(png)).getchannel('A').getbbox())
        self.assertLess(bboxes[0][0], bboxes[1][0]); self.assertLess(bboxes[0][1], bboxes[1][1])

    def test_layout_validation_clamps(self):
        result = app.parse_cover_layout({'title_x': 5, 'logo_y': float('nan'), 'title_size': -3, 'title_color': 'bad'})
        self.assertEqual(result['title_x'], .92)
        self.assertEqual(result['logo_y'], app.COVER_DEFAULT_LAYOUT['logo_y'])
        self.assertEqual(result['title_size'], 12)
        self.assertEqual(result['title_color'], '#1F1F1F')


if __name__ == '__main__': unittest.main()
