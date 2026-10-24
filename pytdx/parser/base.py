# coding=utf-8

from pytdx.log import DEBUG, log
import zlib
import struct
import datetime

class SocketClientNotReady(Exception):
    pass


class SendPkgNotReady(Exception):
    pass


class SendRequestPkgFails(Exception):
    pass


class ResponseHeaderRecvFails(Exception):
    pass


class ResponseRecvFails(Exception):
    pass

RSP_HEADER_LEN = 0x10

class BaseParser(object):

    def __init__(self, client, lock=None):
        self.client = client
        self.data = None
        self.send_pkg = None

        self.rsp_header = None
        self.rsp_body = None
        self.rsp_header_len = RSP_HEADER_LEN
        self.retry_send = 1

        if lock:
            self.lock = lock
        else:
            self.lock = None

    def setParams(self, *args, **xargs):
        """
        构建请求
        :return:
        """
        pass

    def parseResponse(self, body_buf):
        pass

    def setup(self):
        pass


    def call_api(self):
        if self.lock:
            with self.lock:
                log.debug("sending thread lock api call")
                result = self._call_api()
        else:
            result = self._call_api()
        return result

    def _call_api(self):

        self.setup()

        if not(self.client):
            raise SocketClientNotReady("socket client not ready")

        if not(self.send_pkg):
            raise SendPkgNotReady("send pkg not ready")

        nsended = 0
        request = memoryview(self.send_pkg)
        while nsended < len(request):
            sent = self.client.send(request[nsended:])
            if sent <= 0:
                raise SendRequestPkgFails("send fails")
            nsended += sent
            self.client.send_pkg_bytes += sent
        self.client.send_pkg_num += 1
        self.client.last_api_send_bytes = nsended

        if self.client.first_pkg_send_time is None:
            self.client.first_pkg_send_time = datetime.datetime.now()

        if DEBUG:
            log.debug("send package:" + str(self.send_pkg))
        head_buf = bytearray()
        while len(head_buf) < self.rsp_header_len:
            buf = self.client.recv(self.rsp_header_len - len(head_buf))
            self.client.recv_pkg_num += 1
            self.client.recv_pkg_bytes += len(buf)
            if not buf:
                raise ResponseHeaderRecvFails("head_buf is not 0x10 : " + str(head_buf))
            head_buf.extend(buf)

        if DEBUG:
            log.debug("recv head_buf:" + str(head_buf) + " |len is :" + str(len(head_buf)))
        _, _, _, zipsize, unzipsize = struct.unpack("<IIIHH", head_buf)
        self.retry_send = 1 if unzipsize == 30733 else 0
        if DEBUG:
            log.debug("zip size is: " + str(zipsize))

        body_buf = bytearray()
        last_api_recv_bytes = self.rsp_header_len
        while len(body_buf) < zipsize:
            buf = self.client.recv(zipsize - len(body_buf))
            self.client.recv_pkg_num += 1
            self.client.recv_pkg_bytes += len(buf)
            last_api_recv_bytes += len(buf)
            if not buf:
                self.client.last_api_recv_bytes = last_api_recv_bytes
                log.debug("接收数据体失败服务器断开连接")
                raise ResponseRecvFails("接收数据体失败服务器断开连接")
            body_buf.extend(buf)
        self.client.last_api_recv_bytes = last_api_recv_bytes

        if zipsize == unzipsize:
            log.debug("不需要解压")
        else:
            log.debug("需要解压")
            body_buf = zlib.decompress(body_buf)
        if DEBUG:
            log.debug("recv body: ")
            log.debug(body_buf)
        return self.parseResponse(body_buf)


