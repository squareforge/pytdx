# coding: utf-8

from struct import calcsize, unpack
from pytdx.crawler.base_crawler import BaseCralwer
import io
import tempfile
import zipfile
import pandas as pd

"""
https://github.com/rainx/pytdx/issues/133

获取历史财务数据的接口，参考上面issue里面 @datochan 的方案和代码

"""

class HistoryFinancialListCrawler(BaseCralwer):

    def __init__(self):
        self.mode = "content"

    def get_url(self, *args, **kwargs):
        return "https://gitee.com/yutiansut/QADATA/raw/master/financial/content.txt"
    
    def get_content(self, reporthook=None, path_to_download=None, proxies=None, chunksize=1024 * 50, *args, **kwargs):
        from pytdx.hq import TdxHq_API
        api = TdxHq_API()
        api.need_setup = False
        # calc.tdx.com.cn, calc2.tdx.com.cn
        with api.connect(ip="120.76.152.87"):
            content = api.get_report_file_by_size("tdxfin/gpcw.txt")
            if path_to_download is None:
                download_file = tempfile.NamedTemporaryFile(delete=True)
            else:
                download_file = open(path_to_download, 'wb+')
            download_file.write(content)    
            download_file.seek(0)
            return download_file

    def parse(self, download_file, *args, **kwargs):
        content = download_file.read()
        content = content.decode("utf-8")

        def list_to_dict(l):
            return {
                'filename': l[0],
                'hash': l[1],
                'filesize': int(l[2])
            }
        result = [list_to_dict(l) for l in [line.strip().split(",") for line in content.strip().split('\n')]]
        return result


class HistoryFinancialCrawler(BaseCralwer):

    def __init__(self):
        self.mode = "http"

    def get_url(self, *args, **kwargs):
        if 'filename' in kwargs:
            filename = kwargs['filename']
        else:
            raise Exception("Param filename is not set")

        return "http://data.tdx.com.cn/tdxfin/{}".format(filename)

    
    def get_content(self, reporthook=None, path_to_download=None, proxies=None, chunksize=1024 * 50, *args, **kwargs):
        if 'filename' in kwargs:
            filename = kwargs['filename']
        else:
            raise Exception("Param filename is not set")

        if "filesize" in kwargs:
            filesize = kwargs["filesize"]
        else:
            filesize = 0

        from pytdx.hq import TdxHq_API
        last_error = None
        for host in ("data.tdx.com.cn", "120.76.152.87"):
            api = TdxHq_API()
            api.need_setup = False
            try:
                if not api.connect(ip=host):
                    last_error = IOError("could not connect to {}".format(host))
                    continue
                content = api.get_report_file_by_size(
                    "tdxfin/" + filename, filesize=filesize, reporthook=reporthook)
                if not content:
                    last_error = IOError("empty financial report from {}".format(host))
                    continue
                if path_to_download is None:
                    download_file = tempfile.NamedTemporaryFile(delete=True)
                else:
                    download_file = open(path_to_download, 'wb+')
                download_file.write(content)
                download_file.seek(0)
                return download_file
            except Exception as exc:
                last_error = exc
            finally:
                api.disconnect()
        raise IOError("could not download financial report {}: {}".format(filename, last_error))

    def parse(self, download_file, *args, **kwargs):
        download_file.seek(0)
        if zipfile.is_zipfile(download_file):
            download_file.seek(0)
            with zipfile.ZipFile(download_file) as archive:
                names = [name for name in archive.namelist() if name.lower().endswith('.dat')]
                if not names:
                    raise ValueError("no dat file found in zip archive")
                with io.BytesIO(archive.read(names[0])) as datfile:
                    return self._parse_dat(datfile)
        download_file.seek(0)
        return self._parse_dat(download_file)

    def _parse_dat(self, datfile):
        header_pack_format = '<1hI1H3L'
        header_size = calcsize(header_pack_format)
        stock_item_size = calcsize("<6s1c1L")
        data_header = datfile.read(header_size)
        stock_header = unpack(header_pack_format, data_header)
        max_count = stock_header[2]
        report_date = stock_header[1]
        report_size = stock_header[4]
        report_fields_count = int(report_size / 4)
        report_pack_format = '<{}f'.format(report_fields_count)

        results = []
        for stock_idx in range(0, max_count):
            datfile.seek(header_size + stock_idx * calcsize("<6s1c1L"))
            si = datfile.read(stock_item_size)
            stock_item = unpack("<6s1c1L", si)
            code = stock_item[0].decode("utf-8")
            foa = stock_item[2]
            datfile.seek(foa)

            info_data = datfile.read(calcsize(report_pack_format))
            cw_info = unpack(report_pack_format, info_data)
            one_record = (code, report_date) + cw_info
            results.append(one_record)

        return results

    def to_df(self, data):
        if len(data) == 0:
            return None

        total_lengh = len(data[0])
        col = ['code', 'report_date']

        length = total_lengh - 2
        for i in range(0, length):
            col.append("col" + str(i + 1))


        df =  pd.DataFrame(data=data, columns=col)
        # df.to_csv("./a.csv",index=False)
        df.set_index('code', inplace=True)
        return df


if __name__ == '__main__':
    import pandas as pd
    from pytdx.crawler.base_crawler import demo_reporthook
    crawler = HistoryFinancialListCrawler()
    #
    list_data = crawler.fetch_and_parse(reporthook=demo_reporthook)
    df = pd.DataFrame(data=list_data)

    print(df["filename"])
    print(df["filename"].str.contains("gpcw20190630.zip").any())

    # result = datacrawler.parse(download_file=fp)
    # print(datacrawler.to_df(data=result))
    # 读取其中一个
    
    filename = list_data[1]['filename']
    filesize = list_data[1]["filesize"]
    
    datacrawler = HistoryFinancialCrawler()
    pd.set_option('display.max_columns', None)

    # result = datacrawler.fetch_and_parse(reporthook=demo_reporthook, filename=filename, filesize=filesize, path_to_download="./tmpfile.zip")
    # print(result)
    with open(r"D:/stock/gjzq/vipdoc/cw/gpcw20200630.zip", "rb") as fp:
        result = datacrawler.parse(download_file=fp)
        print(datacrawler.to_df(data=result))
