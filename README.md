# pytdx

pytdx 是使用 Python 实现的通达信行情协议客户端。这个仓库基于 [rainx/pytdx](https://github.com/rainx/pytdx)，继续维护标准行情、扩展行情、通达信数据文件读取和历史财务数据解析等功能。

## 本分支改动

- 仅支持 Python 3.8 及以上版本，移除 Python 2 分支和 `six` 依赖。
- 修复 TCP 请求短发送、响应头分片及响应体不完整时的处理。
- 连接或初始化失败时关闭 socket，并保留原始异常信息。
- 修复历史逐笔接口对字符串日期的处理。
- 修复 F10 内容拼接解码和历史财务文件下载、解析问题。

`TdxHq_API` 现有公开方法的名称和参数保持不变。

## 安装

在当前源码目录安装：

```bash
python -m pip install -e .
```

从本 fork 安装：

```bash
python -m pip install 'git+https://github.com/squareforge/pytdx.git'
```

## 功能与文档

- [标准行情 `pytdx.hq`](docs/pytdx_hq.md)：K 线、报价、证券列表、分时、逐笔和 F10 等。
- [扩展行情 `pytdx.exhq`](docs/pytdx_exhq.md)：期货、期权等扩展市场数据。
- [本地数据文件 `pytdx.reader`](docs/pytdx_reader.md)：读取通达信导出的行情文件。
- [历史财务数据](docs/pytdx_crawler.md)：下载和解析历史专业财务数据。
- [交易相关接口](docs/pytdx_trade.md)：通过 TdxTradeServer 使用交易接口。
- [命令行工具](docs/hqget.md)：使用 `hqget` 查询和导出行情；`hqreader` 的用法见[这里](docs/hqreader.md)。
- [连接池](docs/pytdx_pool.md)：备用连接和故障切换，仍属于试验功能。

更多说明见[文档目录](docs/index.md)。

## 说明

pytdx 直接与兼容通达信协议的行情服务器通信。服务器地址、可用性和返回数据由服务端决定；使用前应自行验证目标服务器和所需接口。

原项目作者及贡献者的历史记录见[上游仓库](https://github.com/rainx/pytdx)。
