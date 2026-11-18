import sys
import unittest
from unittest.mock import patch

from aheadsubs import __main__ as cli


class LocalDevicesTest(unittest.TestCase):
    def test_local_devices_override_the_legacy_default_independently(self):
        with patch.object(cli, "FasterWhisper") as whisper, patch.object(cli, "NllbTranslation") as nllb, \
                patch.object(cli, "configure_cuda") as cuda, patch.object(cli, "Relay") as relay, \
                patch.object(cli, "serve") as server, \
                patch.object(sys, "argv", ["relay", "serve", "--device", "cpu", "--no-vad"]):
            cli.main()
            self.assertEqual(whisper.call_args.args[1], "cpu")
            self.assertEqual(nllb.call_args.args[1], "cpu")
            self.assertEqual(server.call_args.kwargs["local_models"], ["whisper-small", "nllb"])
            cuda.assert_not_called()
            cpu_profile = relay.call_args.args[3]
            sys.argv.extend(["--mt-device", "cuda"])
            cli.main()
            self.assertEqual(whisper.call_args.args[1], "cpu")
            self.assertEqual(nllb.call_args.args[1], "cuda")
            cuda.assert_called_once()
            self.assertNotEqual(cpu_profile, relay.call_args.args[3])
