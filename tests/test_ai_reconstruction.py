import io
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pymupdf as fitz
from PIL import Image, ImageDraw
import app


class AIReconstructionTests(unittest.TestCase):
    def test_model_only_changes_masked_pixels_and_uses_inverse_mask(self):
        class FakeSession:
            def run(self, _outputs, inputs):
                self.inputs = inputs
                return [np.full_like(inputs['image'], 32)]
        session = FakeSession()
        image = np.full((40, 40, 3), 210, dtype=np.uint8)
        mask = np.zeros((40, 40), dtype=np.uint8)
        mask[10:15, 10:15] = 255
        with patch('app.migan_session', return_value=session):
            result = app.migan_inpaint(image, mask)
        self.assertTrue(np.array_equal(result[mask == 0], image[mask == 0]))
        self.assertTrue(np.all(result[mask != 0] == 32))
        self.assertEqual(session.inputs['mask'][0, 0, 11, 11], 0)
        self.assertEqual(session.inputs['mask'][0, 0, 0, 0], 255)

    def test_missing_model_fails_clearly(self):
        with patch.object(app, '_MIGAN_SESSION', None), patch.dict(os.environ, {'MIGAN_MODEL_PATH': '/no/such/model.onnx'}):
            with self.assertRaisesRegex(ValueError, 'not installed'):
                app.migan_session()

    def test_mask_preview_and_invalid_engine(self):
        image = Image.new('RGB', (100, 100), 'white')
        ImageDraw.Draw(image).rectangle((20, 20, 29, 29), fill=(200, 200, 200))
        data = io.BytesIO(); image.save(data, format='PNG')
        doc = fitz.open(); page = doc.new_page(width=100, height=100)
        page.insert_image(page.rect, stream=data.getvalue())
        settings = {'x0': .1, 'y0': .1, 'x1': .4, 'y1': .4, 'color': '#c8c8c8', 'tolerance': 4, 'engine': 'ai'}
        mask = Image.open(io.BytesIO(app.reconstruct_scan(page, settings, preview_mask=True)))
        self.assertEqual(mask.getpixel((50, 50)), (255, 0, 0))
        with self.assertRaisesRegex(ValueError, 'Unknown reconstruction'):
            app.reconstruct_scan(page, {**settings, 'engine': 'bad'})
        doc.close()

    @unittest.skipUnless((app.BASE / 'models' / 'migan_pipeline_v2.onnx').is_file(), 'Optional model not installed')
    def test_ai_preview_and_approved_pdf_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'scan.pdf'
            img = Image.new('RGB', (200, 200), 'white')
            ImageDraw.Draw(img).rectangle((30, 30, 42, 42), fill=(200, 200, 200))
            data = io.BytesIO(); img.save(data, format='PNG')
            doc = fitz.open(); page = doc.new_page(width=200, height=200)
            page.insert_image(page.rect, stream=data.getvalue()); doc.save(path); doc.close()
            settings = dict(x0=.1, y0=.1, x1=.3, y1=.3, color='#c8c8c8', tolerance=3, engine='ai', page=0)
            with patch('app.get_job_state', return_value={'files': {'doc': {'path': str(path)}}}):
                client = app.app.test_client()
                preview = client.post('/api/reconstruct-preview/job/doc/0', json=settings)
                mask = client.post('/api/reconstruct-preview/job/doc/0?mask=1', json=settings)
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(mask.status_code, 200)
            result = app.process_one({'id':'test', 'download_dir':tmp},
                {'path':str(path), 'filename':'scan.pdf', 'page_count':1},
                {'add_cover':False, 'watermark':False, 'scan_reconstruction':{**settings, 'approved':True}})
            self.assertTrue(result['ok'], result)
            with fitz.open(Path(tmp) / result['filename']) as out:
                rendered = Image.open(io.BytesIO(out[0].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes('png')))
                self.assertEqual(rendered.tobytes(), Image.open(io.BytesIO(preview.data)).convert('RGB').tobytes())

    @unittest.skipUnless((app.BASE / 'models' / 'migan_pipeline_v2.onnx').is_file(), 'Optional model not installed')
    def test_actual_model_cpu_inference(self):
        image = np.full((256, 256, 3), 255, dtype=np.uint8)
        image[110:125, 100:120] = 150
        mask = np.zeros((256, 256), dtype=np.uint8)
        mask[110:125, 100:120] = 255
        out = app.migan_inpaint(image, mask)
        self.assertEqual(out.shape, image.shape)
        self.assertTrue(np.array_equal(out[mask == 0], image[mask == 0]))
        self.assertFalse(np.array_equal(out[mask != 0], image[mask != 0]))


if __name__ == '__main__':
    unittest.main()
