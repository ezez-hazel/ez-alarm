{ config, lib, pkgs, ezAlarm, ... }:

with lib;

let
  cfg = config.services.ez-alarm;
in {
  options.services.ez-alarm = {
    enable = mkEnableOption "EZ alarm service";

    roomId = mkOption {
      type = types.str;
      description = "Bilibili live room to monitor.";
    };

    barkUrl = mkOption {
      type = types.str;
      description = "Bark-compatible server base URL. The script posts JSON to ${BARK_URL}/post.";
    };

    cloudflareAccountId = mkOption {
      type = types.str;
      description = "Cloudflare account containing the D1 database.";
    };

    cloudflareApiToken = mkOption {
      type = types.str;
      description = "API token needs Account > D1 > Edit permission.";
    };

    cloudflareBarkD1DatabaseId = mkOption {
      type = types.str;
      description = "D1 database ID, not the database name.";
    };

    timer = mkOption {
      type = types.submodule {
        options = {
          onBootSec = mkOption {
            type = types.str;
            default = "2min";
            description = "Time to wait after boot before starting the timer.";
          };

          onUnitActiveSec = mkOption {
            type = types.str;
            default = "5min";
            description = "Time to wait after the last activation of the unit before starting the timer again.";
          };
        };
      };
      description = "Timer configuration options.";
    };
  };

  config = mkIf cfg.enable {
    systemd.timers."ez-alarm" = {
      description = "Run ez-alarm periodically";
      wantedBy = [ "timers.target" ];
        timerConfig = {
          OnBootSec = cfg.timerOnBootSec;
          OnUnitActiveSec = cfg.timerOnUnitActiveSec;
          Unit = "ez-alarm.service";
        };
    };

    systemd.services."ez-alarm" = {
      description = "Check Bilibili live room and send Bark alarm";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      environment = {
        ROOM_ID = cfg.roomId;
        BARK_URL = cfg.barkUrl;
        CLOUDFLARE_ACCOUNT_ID = cfg.cloudflareAccountId;
        BARK_D1_DATABASE_ID = cfg.cloudflareBarkD1DatabaseId;
        CLOUDFLARE_API_TOKEN = cfg.cloudflareApiToken;
      };
      serviceConfig = {
        Type = "oneshot";
        User = "root";
        StateDirectory = "ez-alarm";
        StateDirectoryMode = "0750";
        ExecStart = "${ezAlarm}/bin/ez-alarm";
      };
      wantedBy = [ "multi-user.target" ];
    };
  };
}