import io
import struct
import unittest
import zipfile
from unittest.mock import patch

from pytdx.crawler.history_financial_crawler import HistoryFinancialCrawler
from pytdx.hq import TdxHq_API
from pytdx.parser.get_company_info_content import GetCompanyInfoContent


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
