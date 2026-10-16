# T51B 服务闸与 case 提示验收

- [x] R1 server.py 静态闸放行（FC-3）：`/static/plus/` 加入 only_synthetic 403 前缀判断，`python -m py_compile server.py` 通过
- [x] R2 viewer_plus.html 非法 `?case=` 提示（FC-9）：`console.warn` 记录原始非法值 + 页面顶部 5 秒淡出提示；allowed 白名单 / base / vsBase 逻辑零改动

## 备份 MD5

| 文件 | MD5 |
| --- | --- |
| server.py.bak-T51B | 01492BFA9FA69D7D8BC05088FB04E896 |
| viewer_plus.html.bak-T51B | D02826EA2CDBAD5DBEB83BE96F1BFA6B |
