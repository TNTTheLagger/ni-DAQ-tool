import tkinter as tk
import unittest

import ni_usb6363_monitor as mod


class TestHardwareConstants(unittest.TestCase):
    def test_ai_channels_count(self):
        self.assertEqual(len(mod.AI_CHANNEL_NAMES), 32)

    def test_ai_channel_names(self):
        self.assertEqual(mod.AI_CHANNEL_NAMES[0], "ai0")
        self.assertEqual(mod.AI_CHANNEL_NAMES[31], "ai31")

    def test_ao_channels_count(self):
        self.assertEqual(len(mod.AO_CHANNEL_NAMES), 4)

    def test_ao_channel_names(self):
        self.assertEqual(mod.AO_CHANNEL_NAMES[0], "ao0")
        self.assertEqual(mod.AO_CHANNEL_NAMES[3], "ao3")

    def test_di_lines_count(self):
        self.assertEqual(len(mod.DI_LINE_NAMES), 32)

    def test_do_lines_count(self):
        self.assertEqual(len(mod.DO_LINE_NAMES), 16)

    def test_ranges(self):
        self.assertEqual(mod.AI_MIN, -10.0)
        self.assertEqual(mod.AI_MAX, 10.0)
        self.assertEqual(mod.AO_MIN, -10.0)
        self.assertEqual(mod.AO_MAX, 10.0)

    def test_app_constructs_without_device(self):
        root = tk.Tk()
        root.withdraw()
        app = mod.USB6363App(root)
        self.assertIsInstance(app, mod.USB6363App)
        app.root.destroy()

    def test_voltage_clamping(self):
        v = min(max(15.0, mod.AO_MIN, mod.AO_MAX))
        self.assertEqual(v, 10.0)
        v = min(max(-15.0, mod.AO_MIN, mod.AO_MAX))
        self.assertEqual(v, -10.0)


if __name__ == "__main__":
    unittest.main()