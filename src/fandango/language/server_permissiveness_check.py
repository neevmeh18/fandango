# server_permissiveness_check.py

from typing import Callable, Dict, Optional, Any

# === Minimal negative tests (server-side literals corrupted) ===
negative_server_tests = [
# 2) USER response corrupted
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\nGARB\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\n.\r\nQUIT\r\n+OK Bye\r\n",

# 3) PASS response corrupted
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\nGARB\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\n.\r\nQUIT\r\n+OK Bye\r\n",

# 4) LIST single-line response corrupted
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\nGARB\r\nQUIT\r\n+OK Bye\r\n",

# 5) LIST multi-line terminator corrupted
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\nGARB\r\nQUIT\r\n+OK Bye\r\n",

# 6) QUIT response corrupted
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\n.\r\nQUIT\r\nGARB\r\n",
]


def is_too_permissive(
    grammar: Any,
    parse_fn: Callable[[Any, str], Dict[str, Optional[int]]],
) -> bool:
    """
    Check if grammar is too permissive by testing it on negative server inputs.
    Returns True if ANY negative input is accepted (bad), else False.
    """
    for bad_input in negative_server_tests:
        try:
            result = parse_fn(grammar, bad_input)
            if result.get("success"):  # Grammar wrongly accepted a bad server response
                return True
        except Exception as e:
            print("Exception during permissiveness check", e)
            continue
    return False


if __name__ == "__main__":
    print("This file is meant to be imported and used in your scoring pipeline.")
