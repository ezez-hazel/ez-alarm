# ez-alarm

ez-alarm 是一个运行在 Linux 服务器上的 Bilibili 直播提醒服务。它会定期查询指定直播间；当主播开播时，从 Cloudflare D1 的 `devices` 表读取设备，并通过 Bark 兼容服务的 `/post` 接口发送通知。

服务以单次执行的 Python 脚本为核心，并提供 systemd service/timer、安装脚本和 NixOS module，适合部署在 VPS 或其他长期运行的 Linux 主机上。

项目大部分代码及该`README`使用 Github Copilot 完成。

## 特性

- 定期检查 Bilibili 直播间状态。
- 使用 Cloudflare D1 保存和读取通知设备。
- 支持 Bark 兼容的推送服务。
- 使用 systemd timer 每 5 分钟运行一次，并在开机后 2 分钟开始运行。
- 通过 `StateDirectory` 保存锁文件，避免重复执行。
- 提供 Nix Flake package 和 NixOS module。

## 运行要求

- Linux、systemd 和 Python 3。
- 一个可访问的 Bark 兼容服务。
- Cloudflare D1 数据库，其中包含项目所需的 `devices` 表。
- 一个拥有 `Account > D1 > Edit` 权限的 Cloudflare API Token。

## 使用 systemd 安装

安装脚本会安装可执行文件、systemd service/timer，并创建配置文件：

```sh
sudo sh install.sh
sudoedit /etc/ez-alarm/ez-alarm.env
sudo systemctl enable --now ez-alarm.timer
```

配置文件模板见 [`ez-alarm.env.example`](ez-alarm.env.example)。需要填写以下变量：

| 变量                      | 说明                                                      |
| ------------------------- | --------------------------------------------------------- |
| `ROOM_ID`               | 要监控的 Bilibili 直播间 ID。                             |
| `BARK_URL`              | Bark 兼容服务的基础 URL，脚本会请求`${BARK_URL}/post`。 |
| `CLOUDFLARE_ACCOUNT_ID` | D1 数据库所属的 Cloudflare Account ID。                   |
| `BARK_D1_DATABASE_ID`   | D1 数据库 ID，不是数据库名称。                            |
| `CLOUDFLARE_API_TOKEN`  | 具备`Account > D1 > Edit` 权限的 API Token。            |

安装脚本默认使用 `/usr/bin` 和 `/etc/ez-alarm`，也可以覆盖这两个目录：

```sh
sudo PREFIX=/usr/local/bin CONFIG_DIR=/etc/ez-alarm sh install.sh
```

手动执行一次服务并查看日志：

```sh
sudo systemctl start ez-alarm.service
sudo journalctl -u ez-alarm.service -n 50 --no-pager
systemctl list-timers ez-alarm.timer
```

## NixOS

在 `flake.nix` 中添加此项目：

```nix
{
  inputs.ez-alarm.url = "github:ezez-hazel/ez-alarm";

  outputs = { self, nixpkgs, ez-alarm, ... }: {
    nixosConfigurations.vps = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ez-alarm.nixosModules.default
        ({ ... }: {
          services.ez-alarm = {
            enable = true;
            roomId = "1713546334";
            barkUrl = "https://your-bark-server.example";
            cloudflareAccountId = "your-cloudflare-account-id";
            cloudflareBarkD1DatabaseId = "your-bark-d1-database-id";
            cloudflareApiToken = "your-cloudflare-api-token";
            timer = {
              onBootSec = "2min";
              onUnitActiveSec = "5min";
            };
          };
        })
      ];
    };
  };
}
```
