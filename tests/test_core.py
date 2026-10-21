import importlib.machinery
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("language_popup", str(ROOT / "language_flag_popup.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


class LanguagePopupTests(unittest.TestCase):
    def test_focus_change_is_silent(self):
        detector = app.LanguageChangeDetector(required=3, debounce=0.0)
        self.assertFalse(detector.observe('0x409', 100, 1.0))
        self.assertFalse(detector.observe('0x409', 100, 1.1))
        self.assertFalse(detector.observe('0x429', 200, 1.2))
        self.assertFalse(detector.observe('0x429', 200, 1.3))
        self.assertFalse(detector.observe('0x429', 200, 1.4))

    def test_stable_change_in_same_window_emits_once(self):
        detector = app.LanguageChangeDetector(required=3, debounce=0.0)
        detector.observe('0x409', 100, 1.0)
        detector.observe('0x409', 100, 1.1)
        self.assertFalse(detector.observe('0x429', 100, 1.2))
        self.assertFalse(detector.observe('0x429', 100, 1.3))
        self.assertTrue(detector.observe('0x429', 100, 1.4))
        self.assertFalse(detector.observe('0x429', 100, 1.5))

    def test_language_configuration_and_rendering(self):
        cfg = dict(app.DEFAULT_SETTINGS)
        cfg['languages'] = [
            {'id': '1033', 'name': 'English', 'text': 'CUSTOM',
             'flag': 'usa.png', 'enabled': True}
        ]
        app._sync_language_maps(cfg)
        self.assertEqual(app.LANGUAGE_TEXT['0x409'], 'CUSTOM')
        text = app._render_text_base('0x409', cfg)
        self.assertGreater(text.width, 0)
        cfg['display_mode'] = 'flag_text'
        combined = app._render_flag_base('0x409', cfg, 1920)
        self.assertGreater(combined.height, text.height)

    def test_genie_frame_contracts_into_funnel(self):
        source = app.Image.new('RGBA', (240, 140), (59, 130, 246, 255))
        full = app._genie_frame(source, (300, 200), 1.0)
        funnel = app._genie_frame(source, (300, 200), 0.35)
        self.assertEqual(full.getbbox(), (30, 30, 270, 170))
        self.assertLess(funnel.getbbox()[2] - funnel.getbbox()[0], 240)
        self.assertLess(funnel.getbbox()[3] - funnel.getbbox()[1], 140)
        self.assertIn('genie', app.ANIMATION_TYPES)

    def test_persian_text_shaping(self):
        shaped_fa = app.shape_persian("فا")
        self.assertNotEqual(shaped_fa, "فا")
        self.assertEqual(len(shaped_fa), 2)
        shaped_farsi = app.shape_persian("فارسی")
        self.assertNotEqual(shaped_farsi, "فارسی")

    def test_flat_button_invokes_its_command(self):
        try:
            root = app.tk.Tk()
        except app.tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        root.withdraw()
        calls = []
        button = app.FlatButton(root, "Apply", lambda: calls.append("applied"), "#2563EB")
        button.invoke()
        self.assertEqual(calls, ["applied"])
        root.destroy()


if __name__ == '__main__':
    unittest.main()
