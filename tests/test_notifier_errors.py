import unittest
from unittest.mock import patch

import requests

from utils.notifier import _send_to


class NotifierErrorTests(unittest.TestCase):
    def test_network_error_does_not_write_bot_token_to_log(self):
        with patch("utils.notifier.requests.post", side_effect=requests.ConnectionError(
            "Connection failed: https://api.telegram.org/bot123456:secretTOKEN/sendMessage")), \
             self.assertLogs("utils.notifier", level="ERROR") as captured:
            self.assertFalse(_send_to("https://api.telegram.org/bot123456:secretTOKEN",
                                      "user1", "text", None, "title"))
        self.assertNotIn("secretTOKEN", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
