from dictate.client import send_toggle


class FakeConn:
    def __init__(self, reply):
        self._reply = reply
        self.sent = None

    def sendall(self, data):
        self.sent = data

    def recv(self, n):
        return self._reply

    def close(self):
        pass


def test_send_toggle_returns_reply():
    conn = FakeConn(b"recording\n")
    result = send_toggle(connect=lambda: conn)
    assert result == "recording"
    assert conn.sent == b"toggle"
