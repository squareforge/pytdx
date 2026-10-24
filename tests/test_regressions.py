import io
import socket
import struct
import unittest
import zipfile
from unittest.mock import patch

from pytdx.crawler.history_financial_crawler import HistoryFinancialCrawler
from pytdx.hq import TdxHq_API
from pytdx.parser.get_company_info_content import GetCompanyInfoContent
from pytdx.parser.get_history_transaction_data import GetHistoryTransactionData
from pytdx.parser.base import BaseParser, ResponseHeaderRecvFails, ResponseRecvFails
from pytdx.errors import TdxFunctionCallError
from pytdx.errors import TdxConnectionError
from pytdx.base_socket_client import BaseSocketClient


class ProtocolTest(unittest.TestCase):
    def test_history_transaction_date_accepts_text_and_bytes(self):
        for date in (20261023, "20261023", b"20261023"):
            parser = GetHistoryTransactionData(None)
            parser.setParams(0, "000001", 0, 10, date)
            self.assertEqual(struct.unpack_from("<I", parser.send_pkg, 12)[0], 20261023)

    def test_fragmented_tcp_request_and_response(self):
        class FakeSocket:
            def __init__(self, response):
                self.response = response
                self.sent = bytearray()
                self.send_pkg_num = self.send_pkg_bytes = 0
                self.recv_pkg_num = self.recv_pkg_bytes = 0
                self.first_pkg_send_time = None
                self.last_api_send_bytes = self.last_api_recv_bytes = 0

            def send(self, data):
                chunk = bytes(data[:2])
                self.sent.extend(chunk)
                return len(chunk)

            def recv(self, count):
                chunk = self.response[:min(count, 3)]
                self.response = self.response[len(chunk):]
                return chunk

        class EchoParser(BaseParser):
            def setup(self):
                self.send_pkg = b"request"

            def parseResponse(self, body_buf):
                return bytes(body_buf)

        response = struct.pack("<IIIHH", 0, 0, 0, 5, 5) + b"reply"
        client = FakeSocket(response)
        self.assertEqual(EchoParser(client).call_api(), b"reply")
        self.assertEqual(client.sent, b"request")
        self.assertEqual((client.send_pkg_bytes, client.last_api_send_bytes), (7, 7))
        self.assertEqual((client.recv_pkg_bytes, client.last_api_recv_bytes), (21, 21))

        empty = FakeSocket(struct.pack("<IIIHH", 0, 0, 0, 0, 0))
        self.assertEqual(EchoParser(empty).call_api(), b"")

        with self.assertRaises(ResponseHeaderRecvFails):
            EchoParser(FakeSocket(b"short")).call_api()
        with self.assertRaises(ResponseRecvFails):
            EchoParser(FakeSocket(response[:-1])).call_api()

    def test_wrapped_error_retains_cause(self):
        api = TdxHq_API(raise_exception=True)
        with self.assertRaises(TdxFunctionCallError) as caught:
            api.get_security_count(0)
        self.assertIs(caught.exception.__cause__, caught.exception.original_exception)


class SocketLifecycleTest(unittest.TestCase):
    class FakeSocket:
        def __init__(self, connect_error=None, shutdown_error=None):
            self.connect_error = connect_error
            self.shutdown_error = shutdown_error
            self.closed = False

        def settimeout(self, timeout):
            pass

        def connect(self, address):
            if self.connect_error:
                raise self.connect_error

        def shutdown(self, how):
            if self.shutdown_error:
                raise self.shutdown_error

        def close(self):
            self.closed = True

    def test_failed_connect_closes_socket_for_both_error_modes(self):
        for error in (socket.timeout("timed out"), OSError("refused")):
            for raise_exception in (False, True):
                with self.subTest(error=error, raise_exception=raise_exception):
                    client = self.FakeSocket(connect_error=error)
                    api = BaseSocketClient(raise_exception=raise_exception)
                    api.need_setup = False
                    with patch("pytdx.base_socket_client.TrafficStatSocket", return_value=client):
                        if raise_exception:
                            with self.assertRaises(TdxConnectionError) as caught:
                                api.connect("127.0.0.1")
                            self.assertIs(caught.exception.__cause__, error)
                        else:
                            self.assertFalse(api.connect("127.0.0.1"))
                    self.assertTrue(client.closed)
                    self.assertIsNone(api.client)

    def test_setup_failure_closes_connected_socket(self):
        for shutdown_error in (None, OSError("shutdown failed")):
            with self.subTest(shutdown_error=shutdown_error):
                client = self.FakeSocket(shutdown_error=shutdown_error)
                api = TdxHq_API(raise_exception=True)
                with patch("pytdx.base_socket_client.TrafficStatSocket", return_value=client), \
                        patch.object(api, "setup", side_effect=RuntimeError("setup failed")):
                    with self.assertRaisesRegex(RuntimeError, "setup failed"):
                        api.connect("127.0.0.1")
                self.assertTrue(client.closed)
                self.assertIsNone(api.client)

    def test_shutdown_failure_still_closes_socket(self):
        for raise_exception in (False, True):
            with self.subTest(raise_exception=raise_exception):
                client = self.FakeSocket(shutdown_error=OSError("not connected"))
                api = BaseSocketClient(raise_exception=raise_exception)
                api.client = client
                if raise_exception:
                    with self.assertRaises(TdxConnectionError):
                        api.disconnect()
                else:
                    api.disconnect()
                self.assertTrue(client.closed)
                self.assertIsNone(api.client)

    def test_failed_request_reconnects_and_retries(self):
        class RetryOnce:
            def gen(self):
                yield 0

        api = TdxHq_API(auto_retry=True, raise_exception=True)
        api.ip, api.port = "127.0.0.1", 7709
        api.retry_strategy = RetryOnce()
        with patch("pytdx.hq.GetSecurityCountCmd") as command, \
                patch.object(api, "disconnect") as disconnect, \
                patch.object(api, "connect", return_value=api) as connect, \
                patch("pytdx.base_socket_client.time.sleep"):
            command.return_value.call_api.side_effect = [OSError("disconnected"), 42]
            self.assertEqual(api.get_security_count(0), 42)
        disconnect.assert_called_once_with()
        connect.assert_called_once_with("127.0.0.1", 7709)
        self.assertEqual(command.return_value.call_api.call_count, 2)


class CompanyInfoContentTest(unittest.TestCase):
    def test_decodes_gbk_after_joining_response_chunks(self):
        class FakeCommand:
            chunks = iter([(b"\x81", True), (b"\x40", False)])

            def __init__(self, client, lock=None):
                self.retry_send = True

            def setParams(self, market, code, filename, start, length):
                pass

            def call_api(self):
                chunk, self.retry_send = next(self.chunks)
                return chunk

        api = TdxHq_API(raise_exception=True)
        with patch("pytdx.hq.GetCompanyInfoContent", FakeCommand):
            self.assertEqual(api.get_company_info_content(0, "000001", "000001.txt", 0, 2), "丂")

    def test_parser_returns_raw_content(self):
        response = b"\0" * 10 + struct.pack("<H", 2) + b"\x81\x40"
        self.assertEqual(GetCompanyInfoContent(None).parseResponse(response), b"\x81\x40")


class FinancialReportTest(unittest.TestCase):
    @staticmethod
    def make_archive():
        header = struct.pack("<hIHLLL", 0, 20261023, 1, 0, 8, 0)
        offset = len(header) + struct.calcsize("<6scL")
        record = struct.pack("<6scL", b"000001", b"\0", offset)
        data = header + record + struct.pack("<2f", 1.5, 2.5)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("report.dat", data)
        archive.seek(0)
        return archive

    def test_parses_zip_content_without_zip_filename(self):
        result = HistoryFinancialCrawler().parse(self.make_archive())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][:2], ("000001", 20261023))
        self.assertEqual(result[0][2:], (1.5, 2.5))

    def test_tcp_download_falls_back_and_keeps_exact_bytes(self):
        instances = []

        class FakeApi:
            need_setup = True

            def __init__(self):
                self.host = None
                self.disconnected = False
                instances.append(self)

            def connect(self, ip):
                self.host = ip
                return False if ip == "data.tdx.com.cn" else self

            def get_report_file_by_size(self, filename, filesize=0, reporthook=None):
                return b"report"

            def disconnect(self):
                self.disconnected = True

        with patch("pytdx.hq.TdxHq_API", FakeApi):
            with HistoryFinancialCrawler().get_content(filename="sample.zip") as output:
                self.assertEqual(output.read(), b"report")
        self.assertEqual([api.host for api in instances], ["data.tdx.com.cn", "120.76.152.87"])
        self.assertTrue(all(api.disconnected for api in instances))

    def test_report_file_has_no_zero_prefix(self):
        api = TdxHq_API(raise_exception=True)
        with patch.object(api, "get_report_file", side_effect=[
            {"chunksize": 3, "chunkdata": b"abc"},
        ]):
            self.assertEqual(api.get_report_file_by_size("sample", filesize=3), b"abc")


if __name__ == "__main__":
    unittest.main()
