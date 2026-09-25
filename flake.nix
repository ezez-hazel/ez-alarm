{
  description = "EZ alarm NixOS service";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # 1. 定义 Python 环境
      pythonEnv = pkgs.python315;

      # 2. 将根目录的项目打包为一个可执行程序
      ezAlarm = pkgs.stdenv.mkDerivation {
        pname = "ez-alarm";
        version = "0.1.0";

        # 引入项目根目录源码
        src = ./.;

        buildInputs = [ pythonEnv ];

        # 构建与安装步骤：
        # 创建 $out/bin 目录，并将 ez-alarm.py 移动/重命名为无 .py 后缀的文件并赋予 +x
        installPhase = ''
          mkdir -p $out/bin
          
          # 复制 Python 脚本并重命名为 ez-alarm
          cp ez_alarm.py $out/bin/ez-alarm
          
          # 赋予可执行权限 (+x)
          chmod +x $out/bin/ez-alarm

          # 使用 shebang 修正，确保它调用上面定义的 pythonEnv 解释器
          # 这样脚本第一行自动变为：#!/nix/store/.../bin/python
          sed -i '1i\#!/usr/bin/env python3' $out/bin/ez-alarm
          substituteInPlace $out/bin/ez-alarm \
            --replace "#!/usr/bin/env python3" "#!${pythonEnv}/bin/python"
        '';
      };
    in {
      # 导出 Package
      packages.${system}.default = ezAlarm;

      # 导出 NixOS 模块，并将 ezAlarm 作为参数透传给 Service
      nixosModules.default = { config, lib, pkgs, ... }: {
        imports = [ ./modules/ez-alarm.nix ];
        
        # 将打包好的 package 注入到 module 作用域或服务配置中
        config._module.args.ezAlarmPackage = ezAlarm;
      };
    };
}